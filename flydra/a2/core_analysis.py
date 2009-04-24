"""core analysis functions for Flydra tracked data files"""

from __future__ import division
import tables
import tables.flavor
tables.flavor.restrict_flavors(keep=['numpy']) # ensure pytables 2.x
import numpy
import numpy as np
import math, os, sys, hashlib
import scipy.io
import pprint
DEBUG = False

import adskalman.adskalman as adskalman
import flydra.kalman.dynamic_models
import flydra.kalman.flydra_kalman_utils
from flydra.kalman.ori_smooth import ori_smooth
import flydra.analysis.result_utils
import flydra.reconstruct
import flydra.analysis.PQmath as PQmath
import cgtypes # cgkit 1.x

import weakref
import warnings, tempfile
import unittest
import pkg_resources

def rotate_vec(q,v):
    """rotate vector v by quaternion q"""

    # Note -- if you have a lot of vectors per quaternion, it's faster
    # to convert quat to matrix and multiply.

    qv = cgtypes.quat(0, *v) # make quaternion from vector with w=0
    qresult = q*qv*q.inverse()
    return cgtypes.vec3( qresult.x, qresult.y, qresult.z )

def test_rotate_vec():
    q=cgtypes.quat().fromAngleAxis(np.pi,(0,0,1))
    v=cgtypes.vec3(1,0,0)
    expected = cgtypes.vec3(-1,0,0)
    actual=rotate_vec(q,v)
    assert np.allclose( expected, actual )
    if hasattr(q,'rotateVec'):
        # cgkit 2.x check
        assert np.allclose( expected, q.rotateVec(v) )

    q=cgtypes.quat().fromAngleAxis(0.5*np.pi,(0,0,1))
    v=cgtypes.vec3(1,0,0)
    expected = cgtypes.vec3(0,1,0)
    actual=rotate_vec(q,v)
    assert np.allclose( expected, actual )
    if hasattr(q,'rotateVec'):
        # cgkit 2.x check
        assert np.allclose( expected, q.rotateVec(v) )

def check_hack_postmultiply(hack_postmultiply):
    if hack_postmultiply is not None:
        if isinstance( hack_postmultiply, basestring):
            #filename
            txt = file(hack_postmultiply,mode='r').read()
            hack_postmultiply = eval(txt)
        hack_postmultiply = numpy.asarray(hack_postmultiply)
        assert hack_postmultiply.shape == (3,4)
    return hack_postmultiply

class ObjectIDDataError(Exception):
    pass

class NoObjectIDError(ObjectIDDataError):
    pass

class NotEnoughDataToSmoothError(ObjectIDDataError):
    pass

def parse_seq( input ):
    input = input.replace(',',' ')
    seq = map(int,input.split())
    return seq

def fast_startstopidx_on_sorted_array( sorted_array, value ):
    if hasattr(value,'dtype') and sorted_array.dtype != value.dtype:
        warnings.warn('searchsorted is probably very slow because of different dtypes')
    idx_left = sorted_array.searchsorted( value, side='left' )
    idx_right = sorted_array.searchsorted( value, side='right' )
    return idx_left, idx_right

def find_peaks(y,threshold,search_cond=None):
    """find local maxima above threshold in data y

    returns indices of maxima
    """
    if search_cond is None:
        search_cond = numpy.ones(y.shape,dtype=numpy.bool)

    nz = numpy.nonzero(search_cond)[0]
    ysearch = y[search_cond]
    if len(ysearch)==0:
        return []
    peak_idx_search = numpy.argmax(ysearch)
    peak_idx = nz[peak_idx_search]

    # descend y in positive x direction
    new_idx = peak_idx
    curval = y[new_idx]
    if curval < threshold:
        return []

    while 1:
        new_idx += 1
        if new_idx>=len(y):
            break
        newval = y[new_idx]
        if newval>curval:
            break
        curval= newval
    max_idx = new_idx-1

    # descend y in negative x direction
    new_idx = peak_idx
    curval = y[new_idx]
    while 1:
        new_idx -= 1
        if new_idx < 0:
            break
        newval = y[new_idx]
        if newval>curval:
            break
        curval= newval
    min_idx = new_idx+1

    this_peak_idxs = numpy.arange(min_idx,max_idx+1)
    new_search_cond = numpy.array(search_cond,copy=True)
    new_search_cond[this_peak_idxs] = 0

    all_peak_idxs = [peak_idx]
    all_peak_idxs.extend( find_peaks(y,threshold,search_cond=new_search_cond) )
    return all_peak_idxs

def my_decimate(x,q):
    assert isinstance(q,int)

    if q==1:
        return x

    if 0:
        from scipy_utils import decimate as matlab_decimate # part of ads_utils, contains code translated from MATLAB
        return matlab_decimate(x,q)
    elif 0:
        # take qth point
        return x[::q]
    else:
        # simple averaging
        xtrimlen = int(math.ceil(len(x)/q))*q
        lendiff = xtrimlen-len(x)
        xtrim = numpy.zeros( (xtrimlen,), dtype=numpy.float)
        xtrim[:len(x)] = x

        all = []
        for i in range(q):
            all.append( xtrim[i::q] )
        mysum = numpy.sum( numpy.array(all), axis=0)
        result = numpy.zeros_like(mysum)
        result[:-1] = mysum[:-1]/q
        result[-1] = mysum[-1]/ (q-lendiff)
        return result

def compute_ori_quality(*args,**kwargs):
    import orientation_ekf_fitter
    return orientation_ekf_fitter.compute_ori_quality(*args,**kwargs)

class WeakRefAbleDict(object):
    def __init__(self,val,debug=False):
        self.val = val
        self.debug = debug
        if self.debug:
            print 'creating WeakRefAbleDict',self
    def __del__(self):
        if self.debug:
            print 'deleting WeakRefAbleDict',self
    def __getitem__(self,key):
        return self.val[key]

def check_is_mat_file(data_file):
    if isinstance(data_file,WeakRefAbleDict):
        return True
    elif isinstance(data_file,dict):
        return True
    else:
        return False

def get_data(filename):
    warnings.warn('instead of get_data(), use CachingAnalyzer.initial_file_load(filename)',
                  DeprecationWarning)
    return _initial_file_load(filename)

def _initial_file_load(filename):
    extra = {}
    if os.path.splitext(filename)[1] == '.mat':
        mat_data = scipy.io.loadmat(filename,squeeze_me=True)
        mat_data = WeakRefAbleDict(mat_data)
        obj_ids = mat_data['kalman_obj_id']
        obj_ids = obj_ids.astype( numpy.uint32 )
        obs_obj_ids = obj_ids # use as observation length, even though these aren't observations
        unique_obj_ids = numpy.unique(obj_ids)
        is_mat_file = True
        data_file = mat_data
        # XXX probably need to add time_model computation here
    else:
        kresults = tables.openFile(filename,mode='r')
        obj_ids = kresults.root.kalman_estimates.read(field='obj_id')
        extra['frames'] = kresults.root.kalman_estimates.read(field='frame')
        unique_obj_ids = numpy.unique(obj_ids)
        is_mat_file = False
        data_file = kresults
        extra['kresults'] = kresults
        if hasattr(kresults.root,'textlog'):
            try:
                time_model = (
                    flydra.analysis.result_utils.get_time_model_from_data(
                    kresults))
            except flydra.analysis.result_utils.TextlogParseError, err:
                pass
            else:
                if time_model is not None:
                    extra['time_model'] = time_model
        if hasattr(kresults.root.kalman_estimates.attrs,'dynamic_model_name'):
            extra['dynamic_model_name'] = (
                kresults.root.kalman_estimates.attrs.dynamic_model_name)
    return obj_ids, unique_obj_ids, is_mat_file, data_file, extra

def kalman_smooth(orig_rows,
                  dynamic_model_name=None,
                  frames_per_second=None):
    obs_frames = orig_rows['frame']
    if len(obs_frames)<2:
        raise ValueError('orig_rows must have 2 or more rows of data')

    if np.max(obs_frames) <= np.iinfo(np.int64).max: # OK to cast to int64 from uint64
        obs_frames = np.asarray( obs_frames, dtype=np.int64 )

    fstart = obs_frames.min()
    fend = obs_frames.max()
    assert fstart < fend
    frames = numpy.arange(fstart,fend+1, dtype=np.int64)
    if frames.dtype != obs_frames.dtype:
        warnings.warn('searchsorted is probably very slow because of different dtypes')
    idx = frames.searchsorted(obs_frames)

    x = numpy.empty( frames.shape, dtype=numpy.float )
    y = numpy.empty( frames.shape, dtype=numpy.float )
    z = numpy.empty( frames.shape, dtype=numpy.float )
    obj_id_array =  numpy.ma.masked_array( numpy.empty( frames.shape, dtype=numpy.uint32 ),
                                           mask=numpy.ones( frames.shape, dtype=numpy.bool_ ) )

    x[idx] = orig_rows['x']
    y[idx] = orig_rows['y']
    z[idx] = orig_rows['z']
    obj_id_array[idx] = orig_rows['obj_id']

    # assemble observations (in meters)
    obs = numpy.vstack(( x,y,z )).T

    if dynamic_model_name is None:
        dynamic_model_name = 'fly dynamics, high precision calibration, units: mm'
        warnings.warn('No Kalman model specified. Using "%s" for Kalman smoothing'%(dynamic_model_name,))

    model = flydra.kalman.dynamic_models.get_kalman_model(name=dynamic_model_name,dt=(1.0/frames_per_second))
    if model['dt'] != 1.0/frames_per_second:
        raise ValueError('specified fps disagrees with model')

    # initial state guess: postion = observation, other parameters = 0
    ss = model['ss']
    init_x = numpy.zeros( (ss,) )
    init_x[:3] = obs[0,:]

    P_k1=numpy.zeros((ss,ss)) # initial state error covariance guess

    for i in range(0,3):
        P_k1[i,i]=model['initial_position_covariance_estimate']
    for i in range(3,6):
        P_k1[i,i]=model.get('initial_velocity_covariance_estimate',0.0)
    if ss > 6:
        for i in range(6,9):
            P_k1[i,i]=model.get('initial_acceleration_covariance_estimate',0.0)

    if not 'C' in model:
        raise ValueError('model does not have a linear observation matrix "C".')
    xsmooth, Psmooth = adskalman.kalman_smoother(obs,
                                                 model['A'],
                                                 model['C'],
                                                 model['Q'],
                                                 model['R'],
                                                 init_x,
                                                 P_k1,
                                                 valid_data_idx=idx)
    return frames, xsmooth, Psmooth, obj_id_array, idx

def observations2smoothed(obj_id,
                          orig_rows,
                          obj_id_fill_value='orig',
                          frames_per_second=None,
                          dynamic_model_name=None,
                          allocate_space_for_direction=False,
                          ):
    ksii = flydra.kalman.flydra_kalman_utils.KalmanSaveInfo(
        name=dynamic_model_name,
        allocate_space_for_direction=allocate_space_for_direction
        )
    KalmanEstimates = ksii.get_description()
    field_names = tables.Description(KalmanEstimates().columns)._v_names

    if not len(orig_rows):
        raise NotEnoughDataToSmoothError('observations2smoothed() called with '
                                         'no input data')

    #print "orig_rows['frame'][-1]",orig_rows['frame'][-1]

    frames, xsmooth, Psmooth, obj_id_array, fanout_idx = kalman_smooth(orig_rows,
                                                                       frames_per_second=frames_per_second,
                                                                       dynamic_model_name=dynamic_model_name)
    ss = xsmooth.shape[1]
    if ksii.get_save_covariance()=='diag':
        list_of_xhats = [xsmooth[:,i] for i in range(ss)]
        list_of_Ps    = [Psmooth[:,i,i] for i in range(ss)]
    elif ksii.get_save_covariance()=='position':
        list_of_xhats = [xsmooth[:,0],xsmooth[:,1],xsmooth[:,2],
                         xsmooth[:,3],xsmooth[:,4],xsmooth[:,5],
                         ]
        list_of_Ps = [Psmooth[:,0,0],Psmooth[:,0,1],Psmooth[:,0,2],
                      Psmooth[:,1,1],Psmooth[:,1,2],
                      Psmooth[:,2,2],
                      Psmooth[:,3,3],Psmooth[:,4,4],Psmooth[:,5,5],
                      ]
    timestamps = numpy.zeros( (len(frames),))

    if obj_id_fill_value == 'orig':
        obj_id_array2 = obj_id_array.filled( obj_id )
    elif obj_id_fill_value == 'maxint':
        obj_id_array2 = obj_id_array.filled( numpy.iinfo(obj_id_array.dtype).max ) # set unknown obj_id to maximum value (=mask value)
    else:
        raise ValueError("unknown value for obj_id_fill_value")
    list_of_cols = [obj_id_array2,frames,timestamps]+list_of_xhats+list_of_Ps
    if allocate_space_for_direction:

        rawdir_x = np.nan*np.ones( (len(frames),), dtype=np.float32 )
        rawdir_y = np.nan*np.ones( (len(frames),), dtype=np.float32 )
        rawdir_z = np.nan*np.ones( (len(frames),), dtype=np.float32 )

        dir_x = np.nan*np.ones( (len(frames),), dtype=np.float32 )
        dir_y = np.nan*np.ones( (len(frames),), dtype=np.float32 )
        dir_z = np.nan*np.ones( (len(frames),), dtype=np.float32 )

        list_of_cols += [rawdir_x,rawdir_y,rawdir_z,dir_x,dir_y,dir_z]
    assert len(list_of_cols)==len(field_names) # double check that definition didn't change on us
    rows = numpy.rec.fromarrays(list_of_cols,
                                names = field_names)
    return rows, fanout_idx

# def matfile2rows(data_file,obj_id):
#     warnings.warn('using the slow matfile2rows -- use the faster CachingAnalyzer.load_data()')

#     obj_ids = data_file['kalman_obj_id']
#     cond = obj_ids == obj_id
#     if 0:
#         obj_idxs = numpy.nonzero(cond)[0]
#         indexer = obj_idxs
#     else:
#         # benchmarking showed this is 20% faster
#         indexer = cond

#     obj_id_array = data_file['kalman_obj_id'][cond]
#     obj_id_array = obj_id_array.astype(numpy.uint32)
#     id_frame = data_file['kalman_frame'][cond]
#     id_x = data_file['kalman_x'][cond]
#     id_y = data_file['kalman_y'][cond]
#     id_z = data_file['kalman_z'][cond]
#     id_xvel = data_file['kalman_xvel'][cond]
#     id_yvel = data_file['kalman_yvel'][cond]
#     id_zvel = data_file['kalman_zvel'][cond]
#     id_xaccel = data_file['kalman_xaccel'][cond]
#     id_yaccel = data_file['kalman_yaccel'][cond]
#     id_zaccel = data_file['kalman_xaccel'][cond]

#     KalmanEstimates = flydra.kalman.flydra_kalman_utils.KalmanEstimates
#     field_names = tables.Description(KalmanEstimates().columns)._v_names
#     list_of_xhats = [id_x,id_y,id_z,
#                      id_xvel,id_yvel,id_zvel,
#                      id_xaccel,id_yaccel,id_zaccel,
#                      ]
#     z = numpy.nan*numpy.ones(id_x.shape)
#     list_of_Ps = [z,z,z,
#                   z,z,z,
#                   z,z,z,

#                   ]
#     timestamps = numpy.zeros( (len(frames),))
#     list_of_cols = [obj_id_array,id_frame,timestamps]+list_of_xhats+list_of_Ps
#     assert len(list_of_cols)==len(field_names) # double check that definition didn't change on us
#     rows = numpy.rec.fromarrays(list_of_cols,
#                                 names = field_names)

#     return rows

xtable = {'x':'kalman_x',
          'y':'kalman_y',
          'z':'kalman_z',
          'frame':'kalman_frame',
          'xvel':'kalman_xvel',
          'yvel':'kalman_yvel',
          'zvel':'kalman_zvel',
          'obj_id':'kalman_obj_id',
          }

class LazyRecArrayMimic:
    def __init__(self,data_file,obj_id):
        self.data_file = data_file
        obj_ids = self.data_file['kalman_obj_id']
        self.cond = obj_ids == obj_id
    def field(self,name):
        return self.data_file[xtable[name]][self.cond]
    def __getitem__(self,name):
        return self.data_file[xtable[name]][self.cond]
    def __len__(self):
        return numpy.sum(self.cond)

class LazyRecArrayMimic2:
    def __init__(self,data_file,obj_id):
        self.data_file = data_file
        obj_ids = self.data_file['kalman_obj_id']
        self.cond = obj_ids == obj_id
        self.view = {}
        for name in ['x']:
            xname = xtable[name]
            self.view[xname] = self.data_file[xname][self.cond]
    def field(self,name):
        xname = xtable[name]
        if xname not in self.view:
            self.view[xname] = self.data_file[xname][self.cond]
        return self.view[xname]
    def __getitem__(self,name):
        return self.field(name)
    def __len__(self):
        return len(self.view['kalman_x'])

def choose_orientations(rows, directions, frames_per_second=None,
                        velocity_weight_gain=0.5,
                        #min_velocity_weight=0.0,
                        max_velocity_weight=0.9,
                        elevation_up_bias_degrees=45.0, # tip the velocity angle closer +Z by this amount (maximally)
                        up_dir=None,
                        ):
    """Take input data which is wrapped (mod pi) and unwrap it.

    This uses a dynamic programming algorithm. The basic idea is that
    there are 2 constraints: a direction we think we should be
    oriented (with a time-varying weight of how much we believe that
    direction) and the belief that we shouldn't flip between
    orientations. Our belief direction comes from velocity (point in
    the direction of travel) and, optionally, is tipped towards up_dir
    by elevation_up_bias_degrees. The assignment of directions is
    based on the least-cost of there two terms where on each from the
    sign is flipped or not.

    This is heavily inspired by (i.e. some code stolen from) Kristin
    Branson's choose orientations in ctrax (formerly known as mtrax).

    Arguments
    ---------
    rows: structured array
        position and frame number (has columns 'x','y','z','frame') for N frames
    directions: Nx3 array
        direction to choose with is undetermined to a sign flip
    frames_per_second : float like
        framerate, used to determine velocity from position
    velocity_weight_gain : float like
        scale factor of importance to treat speed (units: importance per speed)
    max_velocity_weight : float like
        maximum weight to attribute to velocity term
    elevation_up_bias_degrees : float like
        number of degrees towards up_dir to bias the velocity direction
    up_dir : 3 vector
        direction to bias velocity direction

    Returns
    -------
    directions : Nx3 array
       directions above with sign chosen to minimize cost
    """
    if (up_dir is None) and (elevation_up_bias_degrees != 0):
        #up_dir = np.array([0,0,1],dtype=np.float)
        raise ValueError("up_dir must be specified. "
                         "(Hint: --up-dir='0,0,1')")
    D2R = np.pi/180

    if DEBUG:
        frames = rows['frame']
        if 1:
            cond1 = (128125 < frames) & (frames < 128140 )
            cond2 = (128460 < frames) & (frames < 128490 )
            cond = cond1 | cond2
            idxs = np.nonzero(cond)[0]
        else:
            idxs = np.arange( len(frames) )

    directions = np.array(directions,copy=True) # don't modify input data

    X = np.array([rows['x'], rows['y'], rows['z']]).T
    #ADS print "rows['x'].shape",rows['x'].shape
    assert len(X.shape)==2
    velocity = (X[1:]-X[:-1])*frames_per_second
    #ADS print 'velocity.shape',velocity.shape
    speed = np.sqrt(np.sum(velocity**2,axis=1))
    #ADS print 'speed.shape',speed.shape
    w = velocity_weight_gain*speed
    w = np.min( [max_velocity_weight*np.ones_like(speed), w], axis=0 )
    #w = np.max( [min_velocity_weight*np.ones_like(speed), w], axis=0 )
    #ADS print 'directions.shape',directions.shape
    #ADS print 'w.shape',w.shape

    velocity_direction = velocity/speed[:,np.newaxis]
    if elevation_up_bias_degrees != 0:

        # bias the velocity direction

        rot1_axis = np.cross(velocity_direction, up_dir)

        dist_from_zplus = np.arccos( np.dot(velocity_direction,up_dir))
        bias_radians = elevation_up_bias_degrees*D2R
        rot1_axis[abs(dist_from_zplus)>(np.pi-1e-14)]=up_dir # pathological case
        velocity_biaser = [ cgtypes.quat().fromAngleAxis(bias_radians,ax) for ax in rot1_axis ]
        biased_velocity_direction = [ rotate_vec( velocity_biaser[i],
                                                  cgtypes.vec3(*(velocity_direction[i]))) for i in range(len(velocity))]
        biased_velocity_direction = numpy.array([ [v[0], v[1], v[2]] for v in biased_velocity_direction ])
        biased_velocity_direction[ dist_from_zplus <= bias_radians, : ] = up_dir

        if DEBUG:
            R2D = 180.0/np.pi
            for i in idxs:
                print
                print 'frame %s ====================='%frames[i]
                print 'X[i]',X[i,:]
                print 'X[i+1]',X[i+1,:]
                print 'velocity',velocity[i]
                print
                print 'rot1_axis',rot1_axis[i]
                print 'up_dir',up_dir
                print 'cross',np.cross(velocity_direction[i], up_dir)
                print 'velocity_direction',velocity_direction[i]
                print
                print 'dist_from_zplus',dist_from_zplus[i]
                print 'dist (deg)',(dist_from_zplus[i]*R2D)
                print 'bias_radians',bias_radians
                print
                print 'velocity_biaser',velocity_biaser[i]
                print 'biased_velocity_direction',biased_velocity_direction[i]

    else:
        biased_velocity_direction = velocity_direction

    # allocate space for storing the optimal path
    signs = [1,-1]
    stateprev = np.zeros((len(directions)-1,len(signs)),dtype=bool)

    tmpcost = [0,0]
    costprevnew = [0,0]
    costprev = [0,0]

    # iterate over each time point
    for i in range(1,len(directions)):
        #ADS print 'i',i

        #ADS print 'directions[i]',directions[i]
        #ADS print 'directions[i-1]',directions[i-1]
        if DEBUG and i in idxs:
            print
            #print 'i',i
            print 'frame',frames[i],'='*50
            print 'directions[i]',directions[i]
            print 'directions[i-1]',directions[i-1]
            print 'velocity weight w[i-1]',w[i-1]
            print 'speed',speed[i-1]
            print 'velocity_direction[i-1]',velocity_direction[i-1]
            print 'biased_velocity_direction[i-1]',biased_velocity_direction[i-1]

        for enum_current,sign_current in enumerate(signs):
            direction_current = sign_current*directions[i]
            this_w = w[i-1]
            vel_term = np.arccos( np.dot( direction_current, biased_velocity_direction[i-1] ))
            up_term  = np.arccos( np.dot( direction_current, up_dir))
            #ADS print
            #ADS print 'sign_current',sign_current,'-'*50
            for enum_previous,sign_previous in enumerate(signs):
                direction_previous = sign_previous*directions[i-1]
                ## print 'direction_current'
                ## print direction_current
                ## print 'biased_velocity_direction'
                ## print biased_velocity_direction
                #ADS print 'sign_previous',sign_previous,'-'*20
                #ADS print 'w[i-1]',w[i-1]
                ## a=(1-w[i-1])*np.arccos( np.dot( direction_current, direction_previous))

                ## b=np.dot( direction_current, biased_velocity_direction[i] )
                ## print a.shape
                ## print b.shape

                flip_term = np.arccos( np.dot( direction_current, direction_previous))
                #ADS print 'flip_term',flip_term,'*',(1-w[i-1])
                #ADS print 'vel_term',vel_term,'*',w[i-1]

                cost_current = 0.0
                # old way
                if not np.isnan(vel_term):
                    cost_current += this_w*vel_term
                if not np.isnan(flip_term):
                    cost_current += (1-this_w)*flip_term
                if not np.isnan(up_term):
                    cost_current += (1-this_w)*up_term

                ## if (not np.isnan(direction_current[0])) and (not np.isnan(direction_previous[0])):
                ##     # normal case - no nans
                ##     cost_current = ( (1-w[i-1])*flip_term + w[i-1]*vel_term )
                ##     cost_current = 0.0

                #ADS print 'cost_current', cost_current
                tmpcost[enum_previous] = costprev[enum_previous] + cost_current
                if DEBUG and i in idxs:
                    print '  (sign_current %d)'%sign_current, '-'*10
                    print '  (sign_previous %d)'%sign_previous
                    print '  flip_term',flip_term
                    print '  vel_term',vel_term
                    print '  up_term',up_term
                    print '  cost_current',cost_current

            best_enum_previous = np.argmin( tmpcost )
            ## if DEBUG and i in idxs:
            ##     print 'tmpcost',tmpcost
            ##     print 'enum_current',enum_current
            ##     print 'best_enum_previous',best_enum_previous
            stateprev[i-1,enum_current] = best_enum_previous
            costprevnew[enum_current] = tmpcost[best_enum_previous]
        ## if DEBUG and i in idxs:
        ##     print 'costprevnew',costprevnew
        costprev[:] = costprevnew[:]
    #ADS print '='*100
    #ADS print 'costprev',costprev
    best_enum_current = np.argmin(costprev)
    #ADS print 'best_enum_current',best_enum_current
    sign_current = signs[best_enum_current]
    directions[-1] *= sign_current
    for i in range(len(directions)-2,-1,-1):
        #ADS print 'i',i
        #ADS print 'stateprev[i]',stateprev[i]
        best_enum_current = stateprev[i,best_enum_current]
        #ADS print 'best_enum_current'
        #ADS print best_enum_current
        sign_current = signs[best_enum_current]
        #ADS print 'sign_current',sign_current
        directions[i] *= sign_current

    if DEBUG:
        for i in idxs:
            print 'ultimate directions:'
            print 'frame',frames[i],directions[i]
    return directions

class PreSmoothedDataCache(object):
    def __init__(self):
        self.cache_h5files_by_data_file = {}

    def query_results(self,obj_id,data_file,orig_rows,
                      frames_per_second=None,
                      dynamic_model_name=None,
                      return_smoothed_directions=False,
                      up_dir=None,
                      min_ori_quality_required=None,
                      ori_quality_smooth_len=10,
                      ):
        """query results

        Arguments
        ---------
        min_ori_quality_required - None or float
          None for no requirement, higher for required quality
        """
        if up_dir is None:
            up_dir = np.array([0.0,0.0,1.0])
            ## raise ValueError("up_dir must be specified. "
            ##                  "(Hint: --up-dir='0,0,1')")

        if frames_per_second is None: raise ValueError('frames_per_second must be specified')
        if dynamic_model_name is None: raise ValueError('dynamic_model_name must be specified')

        pdictname = 'params'
        # these values are double checked to ensure they're the same
        param_dict = {'frames_per_second':frames_per_second,
                      'dynamic_model_name':dynamic_model_name,
                      'return_smoothed_directions':return_smoothed_directions,
                      'up_dir':up_dir,
                      'min_ori_quality_required': min_ori_quality_required,
                      'ori_quality_smooth_len':ori_quality_smooth_len,
                      }

        # get cached datafile for this data_file
        if data_file not in self.cache_h5files_by_data_file:
            orig_hash = flydra.analysis.result_utils.md5sum_headtail(
                data_file.filename)
            expected_title = 'v=2;up_dir=(%.3f, %.3f, %.3f);hash="%s";dynamic_model="%s"'%(
                up_dir[0],up_dir[1],up_dir[2],orig_hash,dynamic_model_name)
            cache_h5file_name = os.path.abspath(os.path.splitext(data_file.filename)[0]) + '.kh5-smoothcache'
            make_new_cache = True
            if os.path.exists( cache_h5file_name ):
                # loading cache file
                try:
                    if int(os.environ.get('CACHE_SAFE','0')):
                        mode='r'
                    else:
                        mode='r+'
                    cache_h5file = tables.openFile(cache_h5file_name, mode=mode)
                except IOError:
                    warnings.warn(
                        'Broken cache file %s. Deleting'%cache_h5file_name)
                    os.unlink( cache_h5file_name )
                else:
                    # check if cache is up to date
                    cache_title = cache_h5file.title
                    if not expected_title == cache_title:
                        if int(os.environ.get('CACHE_DEBUG','0')):
                            sys.stderr.write(
                                'cached file title expected "%s", got "%s"\n'%(
                                expected_title,cache_title))
                    else:
                        if hasattr(cache_h5file.root._v_attrs,pdictname):
                            p = getattr(cache_h5file.root._v_attrs,pdictname)
                            same = True
                            for varname in param_dict:
                                if varname not in p:
                                    if int(os.environ.get('CACHE_DEBUG','0')):
                                        sys.stderr.write(
                                            'cached missing variable %s\n'%(
                                            varname))
                                    same=False
                                    break
                                savedval = p[varname]
                                localval = param_dict[varname]
                                try:
                                    if not localval == savedval:
                                        if (varname == 'return_smoothed_directions'):
                                            if int(os.environ.get('CACHE_DEBUG','0')):
                                                sys.stderr.write(
                                                    'return_smoothed_directions: %s (saved: %s)\n'%(
                                                    return_smoothed_directions,savedval))

                                            if localval == False:
                                                if int(os.environ.get('CACHE_DEBUG','0')):
                                                    sys.stderr.write(
                                                        'cached variable %s changed, but ignoring\n'%(
                                                        varname))
                                            else:
                                                if int(os.environ.get('CACHE_DEBUG','0')):
                                                    sys.stderr.write(
                                                        'cached variable %s changed, but cannot ignore\n'%(
                                                        varname))
                                                    same=False
                                                    break
                                        else:
                                            if int(os.environ.get('CACHE_DEBUG','0')):
                                                sys.stderr.write(
                                                    'cached variable %s changed (current value: %s, cached value: %s)\n'%(
                                                    varname,localval,savedval))
                                                same=False
                                                break
                                except ValueError:
                                    if isinstance(savedval,np.ndarray):
                                        if not (savedval.shape==localval.shape and
                                                np.allclose(savedval,localval)):
                                            if int(os.environ.get('CACHE_DEBUG','0')):
                                                sys.stderr.write(
                                                    'cached variable ndarray %s changed\n'%(
                                                    varname))
                                            same=False
                                            break
                                    else:
                                        raise
                            if same:
                                make_new_cache = False
                    if make_new_cache:
                        if int(os.environ.get('CACHE_SAFE','0')):
                            raise RuntimeError(
                                'cache file %s is stale, but not deleting'%(
                                cache_h5file_name,))
                        else:
                            warnings.warn(
                                'Deleting stale cache file %s.'%cache_h5file_name)
                            cache_h5file.close()
                            os.unlink( cache_h5file_name )

            if make_new_cache:
                # creating cache file
                try:
                    cache_h5file = tables.openFile( cache_h5file_name, mode='w',
                                                    title=expected_title )
                except IOError, err:
                    tmp_trash, cache_h5file_name = tempfile.mkstemp('.h5')
                    # HDF5 doesn't like pre-existing non-HDF5 file
                    os.unlink(cache_h5file_name)
                    cache_h5file = tables.openFile( cache_h5file_name, mode='w',
                                                    title=expected_title )
                except:
                    warnings.warn('error creating cache_h5file %s'%(
                        cache_h5file_name,))
                    raise
                setattr(cache_h5file.root._v_attrs,pdictname,param_dict)

            self.cache_h5files_by_data_file[data_file] = cache_h5file

        h5file = self.cache_h5files_by_data_file[data_file]

        # load or create cached rows for this obj_id
        unsmoothed_tablename = 'obj_id%d'%obj_id
        smoothed_tablename = 'smoothed_'+unsmoothed_tablename

        def _get_group_for_obj(obj_id):
            groupnum = obj_id//2000
            groupname = 'group%d'%groupnum
            if not hasattr(h5file.root,groupname):
                h5file.createGroup(h5file.root,groupname,'cache data')
            return getattr(h5file.root,groupname)

        h5group = _get_group_for_obj(obj_id)

        if hasattr(h5group,smoothed_tablename):
            # pre-existing table is found
            h5table = getattr(h5group,smoothed_tablename)
            rows = h5table[:]
            if not return_smoothed_directions:
                # force users to ask for smoothed directions if they are wanted.
                rows['dir_x'] = np.nan
                rows['dir_y'] = np.nan
                rows['dir_z'] = np.nan
        elif hasattr(h5group,unsmoothed_tablename) and (not return_smoothed_directions):
            # pre-existing table is found
            h5table = getattr(h5group,unsmoothed_tablename)
            rows = h5table[:]
        else:
            # pre-existing table NOT found
            h5table = None
            have_body_axis_information = 'hz_line0' in orig_rows.dtype.fields
            rows, fanout_idx = observations2smoothed(
                obj_id,orig_rows,
                frames_per_second=frames_per_second,
                dynamic_model_name=dynamic_model_name,
                allocate_space_for_direction=have_body_axis_information,
                )

            if have_body_axis_information:
                orig_hzlines = numpy.array([orig_rows['hz_line0'],
                                            orig_rows['hz_line1'],
                                            orig_rows['hz_line2'],
                                            orig_rows['hz_line3'],
                                            orig_rows['hz_line4'],
                                            orig_rows['hz_line5']]).T
                hzlines = np.nan*np.ones( (len(rows),6) )
                for i,orig_hzline in zip(fanout_idx,orig_hzlines):
                    hzlines[i,:] = orig_hzline

                # compute 3 vecs
                directions = flydra.reconstruct.line_direction(hzlines)
                # make consistent

                if min_ori_quality_required is not None:
                    quality_array = compute_ori_quality(
                        data_file, orig_rows['frame'],
                        obj_id, smooth_len=ori_quality_smooth_len)
                    good_cond = quality_array >= min_ori_quality_required
                    bad_cond = ~good_cond
                    directions[bad_cond,:]=np.nan # ignore bad quality data

                if 1:
                    # send kalman-smoothed position estimates (the
                    # velocity will be determined from this)
                    chosen_directions = choose_orientations(
                        rows, directions,
                        frames_per_second=frames_per_second,
                        #velocity_weight=1.0,
                        #max_velocity_weight=1.0,
                        # don't tip the velocity angle
                        elevation_up_bias_degrees=45.0,
                        up_dir=up_dir,
                        )
                rows['rawdir_x'] = chosen_directions[:,0]
                rows['rawdir_y'] = chosen_directions[:,1]
                rows['rawdir_z'] = chosen_directions[:,2]

            if return_smoothed_directions:
                save_tablename = smoothed_tablename
                if 0:
                    smoother = PQmath.QuatSmoother(frames_per_second=frames_per_second,
                                                   beta=1.0,
                                                   percent_error_eps_quats=1,
                                                   )
                    bad_idxs = np.nonzero(np.isnan(directions[:,0]))[0]
                    smooth_directions = smoother.smooth_directions(directions,
                                                                   display_progress=True,
                                                                   no_distance_penalty_idxs=bad_idxs)
                else: # smooth on non-flipped data
                    smooth_directions, smooth_directions_missing = ori_smooth(
                        directions, frames_per_second=frames_per_second,
                        return_missing=True)

                if 1: # (potentially) flip smoothed data as one chunk
                    chosen_smooth_directions_missing = choose_orientations(
                        rows, smooth_directions_missing,
                        frames_per_second=frames_per_second,
                        #velocity_weight=1.0,
                        #max_velocity_weight=1.0,
                        # don't tip the velocity angle
                        elevation_up_bias_degrees=45.0,
                        up_dir=up_dir,
                        )
                    chosen_smooth_directions = np.array(
                        chosen_smooth_directions_missing,copy=True)

                    if not min_ori_quality_required==0:
                        # don't take bad orientations
                        chosen_smooth_directions[np.isnan(smooth_directions)]=np.nan

                rows['dir_x'] = chosen_smooth_directions[:,0]
                rows['dir_y'] = chosen_smooth_directions[:,1]
                rows['dir_z'] = chosen_smooth_directions[:,2]

                if hasattr(h5group,unsmoothed_tablename):
                    # XXX todo: delete un-smoothed table once smoothed version is
                    # made.
                    warnings.warn('implementation detail: should drop unsmoothed table')
            else:
                save_tablename = unsmoothed_tablename

            if h5table is None:
                if 1:
                    filters = tables.Filters(1, complib='lzo') # compress
                else:
                    filters = tables.Filters(0)

                try:
                    h5file.createTable(h5group,
                                       save_tablename,
                                       rows,
                                       filters=filters)
                except:
                    sys.stderr.write('ERROR when using file %s\n'%cache_h5file_name)
                    raise
            else:
                raise NotImplementedError('apprending to existing table not supported')
        return rows


def detect_saccades(rows,
                    frames_per_second=None,
                    method='position based',
                    method_params=None,
                    ):
    """detect saccades defined as exceeding a threshold in heading angular velocity

    arguments:
    ----------
    rows - a structured array such as that returned by load_data()

    method_params for 'position based':
    -----------------------------------
    'downsample' - decimation factor
    'threshold angular velocity (rad/s)' - threshold for saccade detection
    'minimum speed' - minimum velocity for detecting a saccade
    'horizontal only' - only use *heading* angular velocity and *horizontal* speed (like Tamerro & Dickinson 2002)

    returns:
    --------
    results - dictionary, see below

    results dictionary contains:
    -----------------------------------
    'frames' - array of ints, frame numbers of moment of saccade
    'X' - n by 3 array of floats, 3D position at each saccade

    """
    if method_params is None:
        method_params = {}

    RAD2DEG = 180/numpy.pi
    DEG2RAD = 1.0/RAD2DEG

    results = {}

    if method == 'position based':
        ##############
        # load data
        framesA = rows['frame'] # time index A - original time points
        xsA = rows['x']
        ysA = rows['y']
        zsA = rows['z']
        XA = numpy.vstack((xsA,ysA,zsA)).T

        time_A = (framesA - framesA[0])/frames_per_second

        ##############
        # downsample
        skip = method_params.get('downsample',3)

        Aindex = numpy.arange(len(framesA))
        AindexB = my_decimate( Aindex, skip )
        AindexB = numpy.round(AindexB).astype(numpy.int)

        xsB = my_decimate(xsA,skip) # time index B - downsampled by 'skip' amount
        ysB = my_decimate(ysA,skip)
        zsB = my_decimate(zsA,skip)
        time_B = my_decimate(time_A,skip)

        ###############################
        # calculate horizontal velocity

        # central difference
        xdiffsF = xsB[2:]-xsB[:-2] # time index F - points B, but inside one point each end
        ydiffsF = ysB[2:]-ysB[:-2]
        zdiffsF = zsB[2:]-zsB[:-2]
        time_F = time_B[1:-1]
        AindexF = AindexB[1:-1]

        delta_tBC = skip/frames_per_second # delta_t valid for B and C time indices
        delta_tF = 2*delta_tBC # delta_t valid for F time indices

        xvelsF = xdiffsF/delta_tF
        yvelsF = ydiffsF/delta_tF
        zvelsF = zdiffsF/delta_tF

        ## # forward difference
        ## xdiffsC = xsB[1:]-xsB[:-1] # time index C - midpoints between points B, just inside old B endpoints
        ## ydiffsC = ysB[1:]-ysB[:-1]
        ## zdiffsC = zsB[1:]-zsB[:-1]
        ## time_C = (time_B[1:] + time_B[:-1])*0.5

        ## xvelsC = xdiffsC/delta_tBC
        ## yvelsC = ydiffsC/delta_tBC
        ## zvelsC = zdiffsC/delta_tBC

        horizontal_only = method_params.get('horizontal only',True)

        if horizontal_only:
            ###################
            # calculate heading

            ## headingsC = numpy.arctan2( ydiffsC, xdiffsC )
            headingsF = numpy.arctan2( ydiffsF, xdiffsF )

            ## headingsC_u = numpy.unwrap(headingsC)
            headingsF_u = numpy.unwrap(headingsF)

           ## # central difference of forward difference
           ## dheadingD_dt = (headingsC_u[2:]-headingsC_u[:-2])/(2*delta_tBC) # index now the same as C, but starts one later
           ## time_D = time_C[1:-1]

           ## # forward difference of forward difference
           ## dheadingE_dt = (headingsC_u[1:]-headingsC_u[:-1])/(delta_tBC) # index now the same as B, but starts one later
           ## time_E = (time_C[1:]+time_C[:-1])*0.5

            # central difference of central difference
            dheadingG_dt = (headingsF_u[2:]-headingsF_u[:-2])/(2*delta_tF) # index now the same as F, but starts one later
            time_G = time_F[1:-1]

            ## # forward difference of central difference
            ## dheadingH_dt = (headingsF_u[1:]-headingsF_u[:-1])/(delta_tF) # index now the same as B?, but starts one later
            ## time_H = (time_F[1:]+time_F[:-1])*0.5

            if DEBUG:
                import pylab
                pylab.figure()
                #pylab.plot( time_D, dheadingD_dt*RAD2DEG, 'k.-', label = 'forward, central')
                #pylab.plot( time_E, dheadingE_dt*RAD2DEG, 'r.-', label = 'forward, forward')
                pylab.plot( time_G, dheadingG_dt*RAD2DEG, 'g.-', lw = 2, label = 'central, central')
                #pylab.plot( time_H, dheadingH_dt*RAD2DEG, 'b.-', label = 'central, forward')
                pylab.legend()
                pylab.xlabel('s')
                pylab.ylabel('deg/s')

            if DEBUG:
                import pylab
                pylab.figure()
                frame_G = framesA[AindexF][1:-1]
                pylab.plot( frame_G, dheadingG_dt*RAD2DEG, 'g.-', lw = 2, label = 'central, central')
                pylab.legend()
                pylab.xlabel('frame')
                pylab.ylabel('deg/s')

        else: # not horizontal only

            #central diff
            velsF = numpy.vstack((xvelsF,yvelsF,zvelsF)).T
            speedsF = numpy.sqrt(numpy.sum(velsF**2,axis=1))
            norm_velsF = velsF / speedsF[:,numpy.newaxis] # make norm vectors ( mag(x)=1 )
            delta_tG = delta_tF
            cos_angle_diffsG = [] # time base K - between F
            for i in range(len(norm_velsF)-2):
                v1 = norm_velsF[i+2]
                v2 = norm_velsF[i]
                cos_angle_diff = numpy.dot(v1,v2) # dot product = mag(a) * mag(b) * cos(theta)
                cos_angle_diffsG.append( cos_angle_diff )
            angle_diffG = numpy.arccos(cos_angle_diffsG)
            angular_velG = angle_diffG/(2*delta_tG)

            ## vels2 = numpy.vstack((xvels2,yvels2,zvels2)).T
            ## speeds2 = numpy.sqrt(numpy.sum(vels2**2,axis=1))
            ## norm_vels2 = vels2 / speeds2[:,numpy.newaxis] # make norm vectors ( mag(x)=1 )
            ## cos_angle_diffs = [1] # set initial angular vel to 0 (cos(0)=1)
            ## for i in range(len(norm_vels2)-1):
            ##     v1 = norm_vels2[i+1]
            ##     v2 = norm_vels2[i]
            ##     cos_angle_diff = numpy.dot(v1,v2) # dot product = mag(a) * mag(b) * cos(theta)
            ##     cos_angle_diffs.append( cos_angle_diff )
            ## angle_diff = numpy.arccos(cos_angle_diffs)
            ## angular_vel = angle_diff/delta_t2

        ###################
        # peak detection

        thresh_rad2 = method_params.get('threshold angular velocity (rad/s)',200*DEG2RAD)

        if horizontal_only:
            pos_peak_idxsG = find_peaks(dheadingG_dt,thresh_rad2)
            neg_peak_idxsG = find_peaks(-dheadingG_dt,thresh_rad2)

            peak_idxsG = pos_peak_idxsG + neg_peak_idxsG

            if DEBUG:
                import pylab
                pylab.figure()
                pylab.plot( dheadingG_dt*RAD2DEG  )
                pylab.ylabel('heading angular vel (deg/s)')
                for i in peak_idxsG:
                    pylab.axvline( i )
                pylab.plot( peak_idxsG, dheadingG_dt[peak_idxsG]*RAD2DEG ,'k.')
        else:
            peak_idxsG = find_peaks(angular_velG,thresh_rad2)

        orig_idxsG = numpy.array(peak_idxsG,dtype=numpy.int)

        ####################
        # make sure peak is at time when velocity exceed minimum threshold
        min_vel = method_params.get('minimum speed',0.02)

        orig_idxsF = orig_idxsG+1 # convert G timebase to F
        if horizontal_only:
            h_speedsF = numpy.sqrt(numpy.sum((numpy.vstack((xvelsF,yvelsF)).T)**2,axis=1))
            valid_condF = h_speedsF[orig_idxsF] > min_vel
        else:
            valid_condF = speedsF[orig_idxsF] > min_vel
        valid_idxsF = orig_idxsF[valid_condF]

        ####################
        # output parameters

        valid_idxsA = AindexF[valid_idxsF]
        results['frames'] = framesA[valid_idxsA]
        #results['times'] = time_F[valid_idxsF]
        saccade_times = time_F[valid_idxsF] # don't save - user should use frames and indices
        results['X'] = XA[valid_idxsA]

        if DEBUG and horizontal_only:
            pylab.figure()
            ax=pylab.subplot(2,1,1)
            pylab.plot( time_G,dheadingG_dt*RAD2DEG )
            pylab.ylabel('heading angular vel (deg/s)')
            for t in saccade_times:
                pylab.axvline(t)

            pylab.plot(time_G[peak_idxsG],dheadingG_dt[peak_idxsG]*RAD2DEG,'ko')

            ax=pylab.subplot(2,1,2,sharex=ax)
            pylab.plot( time_F, h_speedsF)
    else:
        raise ValueError('unknown saccade detection algorithm')

    return results

class CachingAnalyzer:

    """
    Usage:

     1. Load a file with CachingAnalyzer.initial_file_load(). (Doing this from
     user code is optional for backwards compatibility. However, if a
     CachingAnalyzer instance does it, that instance will maintain a
     strong reference to the data file, perhaps resulting in large
     memeory consumption.)

     2. get traces with CachingAnalyzer.load_data() (for kalman data)
     or CachingAnalyzer.load_dynamics_free_MLE_position() (for maximum
     likelihood estimates of position without any dynamical model)

    """

    def initial_file_load(self,filename):
        """
        Initial file load to get object ids.

        Parameters
        ----------

        filename : string
            The filename to load

        Returns
        -------

        obj_ids : array
             All object ids. Note, this may be extremely long.
        unique_obj_ids : array
             All unique object ides.
        is_mat_file : boolean
             Was filename a .mat file?
        data_file : File object
             Opened reference to original data file.
        extra : dict
             Dictionary with addtional information.
        """
        if filename not in self.loaded_filename_cache:
            (obj_ids, unique_obj_ids, is_mat_file, data_file,
             extra) = _initial_file_load(filename)

            if 0:
                # Why did I used to have this assertion check?
                diff = numpy.int64(obj_ids[1:])-numpy.int64(obj_ids[:-1])
                # for fast search:
                assert numpy.all(diff >= 0) # make sure obj_ids ascending

            self.loaded_filename_cache[filename] = (obj_ids, unique_obj_ids,
                                                    is_mat_file, extra)
            # maintain only a weak ref to data file:
            self.loaded_filename_cache2[filename] = data_file

        (obj_ids, unique_obj_ids, is_mat_file,
         extra)   = self.loaded_filename_cache[filename]
        data_file = self.loaded_filename_cache2[filename]

        self.loaded_datafile_cache[data_file] = True
        return obj_ids, unique_obj_ids, is_mat_file, data_file, extra

    def has_obj_id(self, obj_id, data_file):
        if self.loaded_datafile_cache[data_file]:
            # previously loaded, just find it in cache
            found = False
            for filename in self.loaded_filename_cache.keys():
                data_file_test = self.loaded_filename_cache2[filename]
                if data_file_test == data_file:
                    found = True
            assert found is True
            (obj_ids, unique_obj_ids, is_mat_file, extra) = self.loaded_filename_cache[filename]
        elif isinstance(data_file,basestring):
            filename = data_file
            obj_ids, unique_obj_ids, is_mat_file, data_file, extra = self.initial_file_load(filename)
            self.keep_references.append( data_file ) # prevent from garbage collection with weakref
        else:
            raise ValueError('data_file was expected to be a filename string or an already-loaded file')
        return obj_id in unique_obj_ids

    def load_observations(self,obj_id,data_file):
        # Deprecated name for load_dynamics_free_MLE_position.
        warnings.warn( "using deprecated method load_observations() "
                       "- use load_dynamics_free_MLE_position() instead.",
                       DeprecationWarning, stacklevel=2 )

        return self.load_dynamics_free_MLE_position(obj_id,data_file)

    def load_dynamics_free_MLE_position(self,obj_id,data_file,
                                        min_ori_quality_required=None,
                                        flystate='both', # 'both', 'walking', or 'flying'
                                        walking_start_stops=None, # list of (start,stop)
                                        with_directions=False):
        """Load maximum likelihood estimate of object position from data_file.

        This estimate is independent of any Kalman-filter dynamics,
        and simply represents the least-squares intersection of the
        rays from each camera's observation.
        """
        is_mat_file = check_is_mat_file(data_file)

        if is_mat_file:
            raise ValueError("observations are not saved in .mat files")

        result_h5_file = data_file
        preloaded_dict = self.loaded_h5_cache.get(result_h5_file,None)
        if preloaded_dict is None:
            preloaded_dict = self._load_dict(result_h5_file)
        kresults = preloaded_dict['kresults']
        # XXX this is slow! Should precompute indexes on file load.
        obs_obj_ids = preloaded_dict['obs_obj_ids']

        if isinstance(obj_id,int) or isinstance(obj_id,numpy.integer):
            # obj_id is an integer, normal case
            idxs = numpy.nonzero(obs_obj_ids == obj_id)[0]
        else:
            # may specify sequence of obj_id -- concatenate data, treat as one object
            idxs = []
            for oi in obj_id:
                idxs.append( numpy.nonzero(obs_obj_ids == oi)[0] )
            idxs = numpy.concatenate( idxs )

        rows = kresults.root.kalman_observations.readCoordinates(idxs)
        if not len(rows):
            raise NoObjectIDError('no data from obj_id %d was found'%obj_id)

        if self.hack_postmultiply is not None:
            warnings.warn('Using postmultiplication hack')

            input = numpy.array([rows['x'], rows['y'], rows['z'], numpy.ones_like(rows['x'])])
            output = numpy.dot(self.hack_postmultiply,input)
            rows['x']=output[0,:]
            rows['y']=output[1,:]
            rows['z']=output[2,:]

        rows = self._filter_rows_on_flystate(rows,flystate,walking_start_stops)

        if with_directions:
            # Fixme: This method should return directions=None if
            # these data aren't in file:
            hzlines = numpy.array([rows['hz_line0'],
                                   rows['hz_line1'],
                                   rows['hz_line2'],
                                   rows['hz_line3'],
                                   rows['hz_line4'],
                                   rows['hz_line5']]).T
            directions = flydra.reconstruct.line_direction(hzlines)
            assert numpy.alltrue(PQmath.is_unit_vector(directions))
            if min_ori_quality_required is not None:
                quality_array = compute_ori_quality(
                    data_file, rows['frame'],
                    obj_id)
                good_cond = quality_array >= min_ori_quality_required
                bad_cond = ~good_cond
                directions[bad_cond,:]=np.nan # ignore bad quality data
            return rows, directions
        else:
            return rows

    def load_data(self,obj_id,data_file,use_kalman_smoothing=True,
                  frames_per_second=None, dynamic_model_name=None,
                  return_smoothed_directions=False,
                  flystate='both', # 'both', 'walking', or 'flying'
                  walking_start_stops=None, # list of (start,stop)
                  up_dir=None,
                  min_ori_quality_required = None,
                  ):
        """Load Kalman state estimates from data_file.

        If use_kalman_smoothing is True, the data are passed through a
        Kalman smoother. If not, the data are directly loaded from the
        Kalman estimates in the file. Typically, this means that the
        forward-filtered data saved in realtime are returned. However,
        if the data file has already been smoothed, this will also
        result in smoothing.


        Arguments
        ---------
        min_ori_quality_required : None or float
          None for no requirement, float for required quality

        Returns
        -------
        rows : recarray
          A recarray containing rows of data.

        """
        # for backwards compatibility, allow user to pass in string identifying filename
        if isinstance(data_file,str):
            warnings.warn('passing data_file as string to '
                          'core_analysis.CachingAnalyzer.load_data()')
            filename = data_file
            obj_ids, unique_obj_ids, is_mat_file, data_file, extra = self.initial_file_load(filename)
            self.keep_references.append( data_file ) # prevent from garbage collection with weakref


        is_mat_file = check_is_mat_file(data_file)

        if up_dir is not None:
            up_dir = np.array(up_dir,dtype=np.float)

        if is_mat_file:
            # We ignore use_kalman_smoothing -- always smoothed
            if 0:
                rows = matfile2rows(data_file,obj_id)
            elif 0:
                rows = LazyRecArrayMimic(data_file,obj_id)
            elif 0:
                rows = LazyRecArrayMimic2(data_file,obj_id)
            elif 1:
                rows = self._get_recarray(data_file,obj_id)
        else:
            result_h5_file = data_file
            preloaded_dict = self.loaded_h5_cache.get(result_h5_file,None)
            if preloaded_dict is None:
                preloaded_dict = self._load_dict(result_h5_file)
            kresults = preloaded_dict['kresults']

            if not use_kalman_smoothing:
                # XXX this is slow! Should precompute indexes on file load.
                obj_ids = preloaded_dict['obj_ids']
                if isinstance(obj_id,int) or isinstance(obj_id,numpy.integer):
                    # obj_id is an integer, normal case
                    idxs = numpy.nonzero(obj_ids == obj_id)[0]
                else:
                    # may specify sequence of obj_id -- concatenate data, treat as one object
                    idxs = []
                    for oi in obj_id:
                        idxs.append( numpy.nonzero(obj_ids == oi)[0] )
                    idxs = numpy.concatenate( idxs )
                rows = kresults.root.kalman_estimates.readCoordinates(idxs)
            else:
                obs_obj_ids = preloaded_dict['obs_obj_ids']

                if isinstance(obj_id,int) or isinstance(obj_id,numpy.integer):
                    # obj_id is an integer, normal case
                    tmp_cond = obs_obj_ids == obj_id
                    tmp_nz = numpy.nonzero(tmp_cond)
                    del tmp_cond
                    if len(tmp_nz):
                        obs_idxs = tmp_nz[0]
                    else:
                        obs_idxs = []
                    del tmp_nz
                else:
                    # may specify sequence of obj_id -- concatenate
                    # data, treat as one object
                    obs_idxs = []
                    for oi in obj_id:
                        tmp_idxes = numpy.nonzero(obs_obj_ids == oi)
                        try:
                            tmp_idx = tmp_idxes[0]
                        except IndexError:
                            raise ValueError('obj_id %s does not exist in '
                                             'observations'%oi)
                        obs_idxs.append( tmp_idx )
                        del tmp_idxes, tmp_idx
                        ## print 'oi',oi
                        ## print 'oi',type(oi)
                        ## print 'len(obs_idxs[-1])',len(obs_idxs[-1])
                        ## print
                    obs_idxs = numpy.concatenate( obs_idxs )

                # Kalman observations are already always in meters, no
                # scale factor needed

                orig_rows = kresults.root.kalman_observations.readCoordinates(
                    obs_idxs)

                if len(orig_rows)==0:
                    raise NoObjectIDError('no data from obj_id %d was found'%obj_id)

                if 1 :
                    warnings.warn('Due to Kalman smoothing, all '
                                  'observations using only 1 camera '
                                  'will be ignored.  This is because '
                                  'the Kalman smoothing process '
                                  'needs multiple camera data to '
                                  'triangulate a position')

                    # filter out observations in which are nan (only 1 camera contributed)
                    cond = ~numpy.isnan(orig_rows['x'])
                    orig_rows = orig_rows[cond]

                    if 0:
                        all_obj_ids = list(numpy.unique(orig_rows['obj_id']))
                        all_obj_ids.sort()
                        for obj_id in all_obj_ids:
                            cond = orig_rows['obj_id']==obj_id
                            print obj_id
                            print orig_rows[cond]
                            print

                elif 0:
                    warnings.warn('using EKF estimates of position as '
                                  'observations to Kalman smoother where only '
                                  '1 camera data present')

                    # replace observations with only one camera by
                    # Extended Kalman Filter estimates

                    cond = numpy.isnan(orig_rows['x'])
                    take_idx = numpy.nonzero( cond )[0]
                    take_frames = orig_rows['frame']
                    take_obj_ids = orig_rows['obj_id']

                    kest_table = kresults.root.kalman_estimates[:]
                    for frame,obj_id,idx in zip(
                        take_frames,take_obj_ids,take_idx):

                        kest_row_idxs = np.nonzero(
                            kest_table['frame'] == frame)[0]
                        kest_rows = kest_table[kest_row_idxs]
                        kest_row_idxs = np.nonzero(
                            kest_rows['obj_id'] == obj_id )[0]

                        if 0:
                            print "frame, obj_id",frame, obj_id
                            print 'orig_rows[idx]'
                            print orig_rows[idx]
                            print "kest_rows[kest_row_idxs]"
                            print kest_rows[kest_row_idxs]
                            print
                        if len( kest_row_idxs )==0:
                            # no estimate for this frame (why?)
                            continue
                        assert len( kest_row_idxs )==1
                        kest_row_idx = kest_row_idxs[0]
                        orig_rows[idx]['x'] = kest_rows[kest_row_idx]['x']
                        orig_rows[idx]['y'] = kest_rows[kest_row_idx]['y']
                        orig_rows[idx]['z'] = kest_rows[kest_row_idx]['z']
                else:
                    warnings.warn('abondoning all observations where only 1 '
                                  'camera data present, and estimating past '
                                  'end of last observation')

                    # another idea would be to implement crazy
                    # EKF-based smoothing...

                if len(orig_rows)<=1:
                    raise NotEnoughDataToSmoothError(
                        'not enough data from obj_id %d was found'%obj_id)

                rows = self._smooth_cache.query_results(
                    obj_id,data_file,orig_rows,
                    frames_per_second=frames_per_second,
                    dynamic_model_name=dynamic_model_name,
                    return_smoothed_directions=return_smoothed_directions,
                    up_dir=up_dir,
                    min_ori_quality_required=min_ori_quality_required,
                    )

        if not len(rows):
            raise NoObjectIDError('no data from obj_id %d was found'%obj_id)

        if self.hack_postmultiply is not None:
            warnings.warn('Using postmultiplication hack')

            input = numpy.array([rows['x'], rows['y'], rows['z'], numpy.ones_like(rows['x'])])
            output = numpy.dot(self.hack_postmultiply,input)
            rows['x']=output[0,:]
            rows['y']=output[1,:]
            rows['z']=output[2,:]
            rows['xvel']=numpy.nan
            rows['yvel']=numpy.nan
            rows['zvel']=numpy.nan


            input = numpy.array([rows['rawdir_x'], rows['rawdir_y'], rows['rawdir_z'], numpy.ones_like(rows['rawdir_x'])])
            output = numpy.dot(self.hack_postmultiply,input)
            # renormalize vectors after hack
            output = flydra.reconstruct.norm_vec(output.T).T
            rows['rawdir_x']=output[0,:]
            rows['rawdir_y']=output[1,:]
            rows['rawdir_z']=output[2,:]

            if return_smoothed_directions:
                input = numpy.array([rows['dir_x'], rows['dir_y'], rows['dir_z'], numpy.ones_like(rows['dir_x'])])
                output = numpy.dot(self.hack_postmultiply,input)
                # renormalize vectors after hack
                output = flydra.reconstruct.norm_vec(output.T).T
                rows['dir_x']=output[0,:]
                rows['dir_y']=output[1,:]
                rows['dir_z']=output[2,:]

        assert flystate in ['both', 'walking', 'flying']
        if walking_start_stops is None:
            walking_start_stops = []

        rows = self._filter_rows_on_flystate(rows,flystate,walking_start_stops)
        return rows

    def _filter_rows_on_flystate(self,rows,flystate,walking_start_stops):
        ############################
        # filter based on flystate
        ############################

        walking_and_flying_kalman_rows = rows # preserve original data
        frame = walking_and_flying_kalman_rows['frame']

        if flystate != 'both':
            if flystate=='flying':
                # assume flying unless we're told it's walking
                state_cond = numpy.ones( frame.shape, dtype=numpy.bool )
            else:
                state_cond = numpy.zeros( frame.shape, dtype=numpy.bool )

            if len(walking_start_stops):
                for walkstart,walkstop in walking_start_stops:
                    frame = walking_and_flying_kalman_rows['frame'] # restore

                    # handle each bout of walking
                    walking_bout = numpy.ones( frame.shape, dtype=numpy.bool)
                    if walkstart is not None:
                        walking_bout &= ( frame >= walkstart )
                    if walkstop is not None:
                        walking_bout &= ( frame <= walkstop )
                    if flystate=='flying':
                        state_cond &= ~walking_bout
                    else:
                        state_cond |= walking_bout

                masked_cond = ~state_cond
                n_filtered = np.sum(masked_cond)
                rows = numpy.ma.masked_where( ~state_cond, walking_and_flying_kalman_rows )
                rows = rows.compressed()
        return rows

    def get_raw_positions(self,
                          obj_id,
                          data_file,
                          use_kalman_smoothing=True,
                          ):
        """get raw data (Kalman smoothed if data has been pre-smoothed)"""
        rows = self.load_data( obj_id,data_file,use_kalman_smoothing=use_kalman_smoothing)
        xsA = rows['x']
        ysA = rows['y']
        zsA = rows['z']

        XA = numpy.vstack((xsA,ysA,zsA)).T
        return XA

    def get_obj_ids(self,data_file):
        is_mat_file = check_is_mat_file(data_file)
        if not is_mat_file:
            result_h5_file = data_file
            preloaded_dict = self.loaded_h5_cache.get(result_h5_file,None)
            if preloaded_dict is None:
                preloaded_dict = self._load_dict(result_h5_file)

        if is_mat_file:
            uoi = numpy.unique(data_file['kalman_obj_id'])
            return uoi
        else:
            preloaded_dict = self.loaded_h5_cache.get(data_file,None)
            return preloaded_dict['unique_obj_ids']

    def calculate_trajectory_metrics(self,
                                     obj_id,
                                     data_file,#result_h5_file or .mat dictionary
                                     use_kalman_smoothing=True,
                                     frames_per_second=None,
                                     method='position based',
                                     method_params=None,
                                     hide_first_point=True, # velocity bad there
                                     dynamic_model_name=None,
                                     ):
        """
        Calculate trajectory metrics.

        Parameters
        ----------
        obj_id : int
            The object id to be analyzed.
        data_file : {string, open pytables file object, dict}
            The file that contains the object id to be analyzed. If
            string, the pytables filename. If dict, the data dict from
            a .mat file.
        frames_per_second : float, optional
            Framerate of data. (If `None`, automatically guessed.)
        use_kalman_smoothing : boolean
            If `False`, use original, causal Kalman filtered data
            (rather than Kalman smoothed observations). Default is
            `True`.
        method_params : dict
            for `position based` may be { 'downsample' :
            decimation_factor } where decimation_factor is the amount
            to downsample.

        Returns
        -------
        results : dict
            Dictionary of results with keys ['time_kalmanized', 'X_kalmanized',
            'frame', 'time_t', 'X_t', 'vels_t', 'speed_t', 'h_speed_t',
            'v_speed_t', 'coarse_heading_t', 'time_dt', 'h_ang_vel_dt',
            'ang_vel_dt']

        """

        rows = self.load_data( obj_id, data_file,use_kalman_smoothing=use_kalman_smoothing,
                               frames_per_second=frames_per_second,
                               dynamic_model_name=dynamic_model_name,
                               )
        numpyerr = numpy.seterr(all='raise')
        try:
            if method_params is None:
                method_params = {}

            RAD2DEG = 180/numpy.pi
            DEG2RAD = 1.0/RAD2DEG

            results = {}

            if method == 'position based':
                ##############
                # load data
                framesA = rows['frame']
                xsA = rows['x']

                ysA = rows['y']
                zsA = rows['z']
                XA = numpy.vstack((xsA,ysA,zsA)).T
                time_A = (framesA - framesA[0])/frames_per_second

                ##############
                # downsample
                skip = method_params.get('downsample',3)

                Aindex = numpy.arange(len(framesA))
                AindexB = my_decimate( Aindex, skip )
                AindexB = numpy.round(AindexB).astype(numpy.int)

                xsB = my_decimate(xsA,skip) # time index B - downsampled by 'skip' amount
                ysB = my_decimate(ysA,skip)
                zsB = my_decimate(zsA,skip)
                time_B = my_decimate(time_A,skip)
                framesB = my_decimate(framesA,skip)

                XB = numpy.vstack((xsB,ysB,zsB)).T

                ###############################
                # calculate horizontal velocity

                # central difference
                xdiffsF = xsB[2:]-xsB[:-2] # time index F - points B, but inside one point each end
                ydiffsF = ysB[2:]-ysB[:-2]
                zdiffsF = zsB[2:]-zsB[:-2]
                time_F = time_B[1:-1]
                frame_F = framesB[1:-1]

                XF = XB[1:-1]
                AindexF = AindexB[1:-1]

                delta_tBC = skip/frames_per_second # delta_t valid for B and C time indices
                delta_tF = 2*delta_tBC # delta_t valid for F time indices

                xvelsF = xdiffsF/delta_tF
                yvelsF = ydiffsF/delta_tF
                zvelsF = zdiffsF/delta_tF

                velsF = numpy.vstack((xvelsF,yvelsF,zvelsF)).T
                speedsF = numpy.sqrt(numpy.sum(velsF**2,axis=1))

                h_speedsF = numpy.sqrt(numpy.sum(velsF[:,:2]**2,axis=1))
                v_speedsF = velsF[:,2]

                headingsF = numpy.arctan2( ydiffsF, xdiffsF )
                #headings2[0] = headings2[1] # first point is invalid

                headingsF_u = numpy.unwrap(headingsF)

                dheadingG_dt = (headingsF_u[2:]-headingsF_u[:-2])/(2*delta_tF) # central difference
                time_G = time_F[1:-1]

                norm_velsF = velsF
                nonzero_speeds = speedsF[:,numpy.newaxis]
                nonzero_speeds[ nonzero_speeds==0 ] = 1
                norm_velsF = velsF / nonzero_speeds # make norm vectors ( mag(x)=1 )
                if 0:
                    #forward diff
                    time_K = (timeF[1:]+timeF[:-1])/2 # same spacing as F, but in between
                    delta_tK = delta_tF
                    cos_angle_diffsK = [] # time base K - between F
                    for i in range(len(norm_velsF)-1):
                        v1 = norm_velsF[i+1]
                        v2 = norm_velsF[i]
                        cos_angle_diff = numpy.dot(v1,v2) # dot product = mag(a) * mag(b) * cos(theta)
                        cos_angle_diffsK.append( cos_angle_diff )
                    angle_diffK = numpy.arccos(cos_angle_diffsK)
                    angular_velK = angle_diffK/delta_tK
                else:
                    #central diff
                    delta_tG = delta_tF
                    cos_angle_diffsG = [] # time base K - between F
                    for i in range(len(norm_velsF)-2):
                        v1 = norm_velsF[i+2]
                        v2 = norm_velsF[i]
                        cos_angle_diff = numpy.dot(v1,v2) # dot product = mag(a) * mag(b) * cos(theta)
                        cos_angle_diffsG.append( cos_angle_diff )
                    cos_angle_diffsG = numpy.asarray( cos_angle_diffsG )

                    # eliminate fp rounding error:
                    cos_angle_diffsG = numpy.clip( cos_angle_diffsG, -1.0, 1.0 )

                    angle_diffG = numpy.arccos(cos_angle_diffsG)
                    angular_velG = angle_diffG/(2*delta_tG)

    ##            times = numpy.arange(0,len(xs))/frames_per_second
    ##            times2 = times[::skip]
    ##            dt_times2 = times2[1:-1]

                if hide_first_point:
                    slicer = slice(1,None,None)
                else:
                    slicer = slice(0,None,None)

                results = {}
                if use_kalman_smoothing:
                    results['kalman_smoothed_rows'] = rows
                results['time_kalmanized'] = time_A[slicer]  # times for position data
                results['X_kalmanized'] = XA[slicer] # raw position data from Kalman (not otherwise downsampled or smoothed)

                results['frame'] = frame_F[slicer] # times for most data
                results['time_t'] = time_F[slicer] # times for most data
                results['X_t'] = XF[slicer]
                results['vels_t'] = velsF[slicer] # 3D velocity
                results['speed_t'] = speedsF[slicer]
                results['h_speed_t'] = h_speedsF[slicer]
                results['v_speed_t'] = v_speedsF[slicer]
                results['coarse_heading_t'] = headingsF[slicer] # in 2D plane (note: not body heading)

                results['time_dt'] = time_G # times for angular velocity data
                results['h_ang_vel_dt'] = dheadingG_dt
                results['ang_vel_dt'] = angular_velG
            else:
                raise ValueError('unknown saccade detection algorithm')
        finally:
            numpy.seterr(**numpyerr)
        return results

    def get_smoothed(self,
                     obj_id,
                     data_file,#result_h5_file or .mat dictionary
                     frames_per_second=None,
                     dynamic_model_name=None,
                     ):
        rows = self.load_data( obj_id, data_file,
                               use_kalman_smoothing=True,
                               frames_per_second=frames_per_second,
                               dynamic_model_name=dynamic_model_name,
                               )
        results = {}
        results['kalman_smoothed_rows'] = rows
        return results

    ###################################
    # Implementatation details below
    ###################################

    # for class CachingAnalyzer
    def __init__(self,hack_postmultiply=None,is_global=False):
        self.hack_postmultiply = check_hack_postmultiply(hack_postmultiply)

        if not is_global:
            warnings.warn("maybe you want to use the global CachingAnalyzer instance? (Call 'get_global_CachingAnalyzer()'.)", stacklevel=2)

        self._smooth_cache = PreSmoothedDataCache()

        self.keep_references = [] # a list of strong references

        self.loaded_h5_cache = {}

        self.loaded_filename_cache = {}
        self.loaded_filename_cache2 = weakref.WeakValueDictionary()

        self.loaded_datafile_cache = weakref.WeakKeyDictionary()

        self.loaded_matfile_recarrays = weakref.WeakKeyDictionary()
        self.loaded_cond_cache = weakref.WeakKeyDictionary()

    def _get_recarray(self,data_file,obj_id,which_data='kalman'):
        """returns a recarray of the data
        """
        full, obj_id2idx = self._load_full_recarray(data_file,which_data=which_data)
        try:
            start,stop = obj_id2idx[obj_id]
        except KeyError,err:
            raise NoObjectIDError('obj_id not found')
        rows = full[start:stop]
        return rows

    def _load_full_recarray( self, data_file, which_data='kalman'):
        assert which_data in ['kalman','observations']

        if which_data != 'kalman':
            raise NotImplementedError('')

        if data_file not in self.loaded_datafile_cache:
            # loading with initial_file_load() ensures that obj_ids are ascending
            raise RuntimeError('you must load data_file using CachingAnalyzer.initial_file_load() (and keep a reference to it, and keep the same CachingAnalyzer instance)')

        if not check_is_mat_file(data_file):
            raise NotImplementedError('loading recarray not implemented yet for h5 files')

        if data_file not in self.loaded_matfile_recarrays:
            # create recarray
            names = xtable.keys()
            xnames = [ xtable[name] for name in names ]
            arrays = [ data_file[xname] for xname in xnames ]
            ra = numpy.rec.fromarrays( arrays, names=names )

            # create obj_id-based indexer
            obj_ids = ra['obj_id']

            uniq = numpy.unique(obj_ids)
            start_idx, stop_idx = fast_startstopidx_on_sorted_array( obj_ids, uniq )
            obj_id2idx = {}
            for i,obj_id in enumerate(uniq):
                obj_id2idx[obj_id] = start_idx[i], stop_idx[i]
            self.loaded_matfile_recarrays[data_file] = ra, obj_id2idx, which_data
        full, obj_id2idx, which_data_test = self.loaded_matfile_recarrays[data_file]

        if which_data != which_data_test:
            raise ValueError('which_data switched between original load and now')

        return full, obj_id2idx

    def _load_dict(self,result_h5_file):
        if isinstance(result_h5_file,str) or isinstance(result_h5_file,unicode):
            kresults = tables.openFile(result_h5_file,mode='r')
            self_should_close = True
        else:
            kresults = result_h5_file
            self_should_close = False
            # XXX I should make my reference a weakref
        obj_ids = kresults.root.kalman_estimates.read(field='obj_id')
        obs_obj_ids = kresults.root.kalman_observations.read(field='obj_id')
        unique_obj_ids = numpy.unique(obs_obj_ids)
        preloaded_dict = {'kresults':kresults,
                          'self_should_close':self_should_close,
                          'obj_ids':obj_ids,
                          'obs_obj_ids':obs_obj_ids,
                          'unique_obj_ids':unique_obj_ids,
                          }
        self.loaded_h5_cache[result_h5_file] = preloaded_dict
        return preloaded_dict

    def close(self):
        for key,preloaded_dict in self.loaded_h5_cache.iteritems():
            if preloaded_dict['self_should_close']:
                preloaded_dict['kresults'].close()
                preloaded_dict['self_should_close'] = False
        for h5file in self._smooth_cache.cache_h5files_by_data_file.itervalues():
            h5file.close()

    def __del__(self):
        self.close()

def test_choose_orientations():
    #                             8     9     10   11  12 13   14   15     16     17     18  19 20
    x = np.array([0,1,2,3,4,5,6,7,7.01, 7.02, 7.03, 8, 9, 100, 101, 100.99,100.98,100.97,100,50,40])
    y = np.zeros_like(x)
    z = np.zeros_like(x)
    frames = np.arange(len(x))
    rows = np.rec.fromarrays([x,y,z,frames],names=['x','y','z','frame'])

    true_directions = np.array([[1.0,0.0,0.0]]*len(x))
    true_directions[18:,:] = [-1,0,0]

    input_directions = np.array(true_directions,copy=True)
    input_directions[9,:] = [-1,0,0]
    input_directions[13,:] = [-1,0,0]

    input_directions[14:,:] = [1,0,0]

    print 'input_directions'
    print input_directions

    result_directions = choose_orientations( rows, input_directions,
                                             frames_per_second=1.0,
                                             velocity_weight_gain=1.0,
                                             max_velocity_weight=1.0,
                                             elevation_up_bias_degrees=0.0,
                                             )
    print 'true_directions'
    print true_directions
    print
    print 'result_directions'
    print result_directions

    assert np.allclose( result_directions, true_directions )

global _global_ca_instance
_global_ca_instance = None

def get_global_CachingAnalyzer(**kwargs):
    """get the global CachingAnalyzer instance

    If a single, global instance of :class:`CachingAnalyzer` has not
    already been constructed, construct it. Regardless, return the the
    global instance.

    Parameters
    ----------
    **kwargs : keyword arguments
       These are passed to the constructor of CachingAnalyzer
       is the global instance has not yet been created.

    Returns
    -------
    ca_instance : CachingAnalyzer instance

    Examples
    --------
    >>> ca = get_global_CachingAnalyzer()

    """
    global _global_ca_instance
    if _global_ca_instance is None:
        _global_ca_instance = CachingAnalyzer(is_global=True,**kwargs)
    return _global_ca_instance

class TestCoreAnalysis(unittest.TestCase):
    def setUp(self):
        self.ca = CachingAnalyzer()

        filename1=pkg_resources.resource_filename(__name__,'sample_kalman_trajectories.h5')
        filename2=pkg_resources.resource_filename(__name__,'sample_kalman_trajectory.mat')

        filenames = [filename1,
                     filename2,
                     ]
        self.test_obj_ids_list = [[497,1369], #filename1
                                  [1606], #filename2
                                  ]

        self.data_files = []
        self.is_mat_files = []
        self.fps = []
        self.dynamic_model = []
        for filename in filenames:
            obj_ids, use_obj_ids, is_mat_file, data_file, extra = self.ca.initial_file_load(filename)
            self.data_files.append( data_file )
            self.is_mat_files.append( is_mat_file )
            fps = 100.0
            kalman_model = 'fly dynamics, high precision calibration, units: mm'
            self.fps.append( fps )
            self.dynamic_model.append(kalman_model)

    def tearDown(self):
        for data_file,is_mat_file in zip(self.data_files,self.is_mat_files):
            if not is_mat_file:
                data_file.close()

    def test_fast_startstopidx_on_sorted_array_scalar(self):
        sorted_array = numpy.arange(10)
        for value in [-1,0,2,5,6,11]:
            idx_fast_start, idx_fast_stop = fast_startstopidx_on_sorted_array( sorted_array, value )
            idx_slow = numpy.nonzero(sorted_array==value)[0]
            idx_fast = numpy.arange( idx_fast_start, idx_fast_stop )
            self.failUnless( idx_fast.shape == idx_slow.shape )
            self.failUnless( numpy.allclose(idx_fast,idx_slow) )

    def test_fast_startstopidx_on_sorted_array_1d(self):
        sorted_array = numpy.arange(10)
        values = [-1,0,2,5,6,11]

        idx_fast_start, idx_fast_stop = fast_startstopidx_on_sorted_array( sorted_array, values )

        for i,value in enumerate(values):
            idx_slow = numpy.nonzero(sorted_array==value)[0]
            if not len(idx_slow):
                self.failUnless( idx_fast_start[i]==idx_fast_stop[i] )
            else:
                self.failUnless( idx_fast_start[i]==idx_slow[0])
                self.failUnless( idx_fast_stop[i]==(idx_slow[-1]+1))

    def test_CachingAnalyzer_nonexistant_object(self):
        for (data_file,is_mat_file) in zip(self.data_files,
                                           self.is_mat_files,
                                           ):
            for use_kalman_smoothing in [True,False]:
                if is_mat_file and not use_kalman_smoothing:
                    # all data is kalman smoothed in matfile
                    continue

                obj_id = 123456789 # does not exist in file
                try:
                    results = self.ca.calculate_trajectory_metrics(obj_id,
                                                                   data_file,
                                                                   use_kalman_smoothing=use_kalman_smoothing,
                                                                   frames_per_second=100.0,
                                                                   method='position based',
                                                                   method_params={'downsample':1,
                                                                                  },
                                                                   dynamic_model_name='fly dynamics, high precision calibration, units: mm',
                                                                   )
                except NoObjectIDError:
                    pass
                else:
                    raise RuntimeError('We should not get here - a NoObjectIDError should be raised')

    def test_smooth(self):
        for data_file,test_obj_ids,is_mat_file,fps,model in zip(self.data_files,
                                                                self.test_obj_ids_list,
                                                                self.is_mat_files,
                                                                self.fps,
                                                                self.dynamic_model,
                                                                ):
            if is_mat_file:
                # all data is kalman smoothed in matfile
                continue
            for obj_id in test_obj_ids:
                ######## 1. load observations
                obs_obj_ids = data_file.root.kalman_observations.read(field='obj_id')
                obs_idxs = numpy.nonzero(obs_obj_ids == obj_id)[0]

                # Kalman observations are already always in meters, no scale factor needed
                orig_rows = data_file.root.kalman_observations.readCoordinates(obs_idxs)

                ######## 2. perform Kalman smoothing
                rows = observations2smoothed(obj_id,orig_rows,
                                                           frames_per_second=fps,
                                                           dynamic_model_name=model,
                                                           )  # do Kalman smoothing

                ######## 3. compare observations with smoothed
                orig = []
                smooth = []

                for i in range(len(rows)):
                    frameno = rows[i]['frame']
                    idxs = numpy.nonzero(orig_rows['frame']==frameno)[0]
                    #print rows[i]
                    if len(idxs):
                        assert len(idxs)==1
                        idx = idxs[0]
                        #print '<-',orig_rows[idx]
                        orig.append( (orig_rows[idx]['x'], orig_rows[idx]['y'], orig_rows[idx]['z']) )
                        smooth.append( (rows[i]['x'], rows[i]['y'], rows[i]['z']) )
                    #print
                orig = numpy.array(orig)
                smooth = numpy.array(smooth)
                dist = numpy.sqrt(numpy.sum((orig-smooth)**2, axis=1))
                mean_dist = numpy.mean(dist)
                #print 'mean_dist',mean_dist
                assert mean_dist < 1.0 # should certainly be less than 1 meter!

    def test_CachingAnalyzer_load_data(self):
        for data_file,test_obj_ids,is_mat_file,fps,model in zip(self.data_files,
                                                                self.test_obj_ids_list,
                                                                self.is_mat_files,
                                                                self.fps,
                                                                self.dynamic_model,
                                                                ):
            for obj_id in test_obj_ids:

            # Test that load_data() loads similar values for (presumably)
            # forward-only filter and smoother.

                rows_smooth = self.ca.load_data(obj_id,
                                                data_file,
                                                use_kalman_smoothing=True,
                                                frames_per_second=fps,
                                                dynamic_model_name=model,
                                                )
                if is_mat_file:
                    # all data is kalman smoothed in matfile
                    continue
                rows_filt = self.ca.load_data(obj_id,
                                              data_file,
                                              use_kalman_smoothing=False,
                                              frames_per_second=fps,
                                              dynamic_model_name=model,
                                              )
                filt = []
                smooth = []
                for i in range(len(rows_smooth)):
                    smooth.append( (rows_smooth['x'][i], rows_smooth['y'][i], rows_smooth['z'][i]) )
                    filt.append( (rows_filt['x'][i], rows_filt['y'][i], rows_filt['z'][i]) )
                filt = numpy.array(filt)
                smooth = numpy.array(smooth)
                dist = numpy.sqrt(numpy.sum((filt-smooth)**2,axis=1))
                mean_dist = numpy.mean(dist)
                assert mean_dist < 0.1

    def test_CachingAnalyzer_calculate_trajectory_metrics(self):
        for data_file,test_obj_ids,is_mat_file,fps,model in zip(self.data_files,
                                                                self.test_obj_ids_list,
                                                                self.is_mat_files,
                                                                self.fps,
                                                                self.dynamic_model,
                                                                ):
            for use_kalman_smoothing in [True,False]:
                for obj_id in test_obj_ids:
                    results = self.ca.calculate_trajectory_metrics(obj_id,
                                                                   data_file,
                                                                   use_kalman_smoothing=use_kalman_smoothing,
                                                                   frames_per_second=fps,
                                                                   dynamic_model_name=model,
                                                                   hide_first_point=False,
                                                                   method='position based',
                                                                   method_params={'downsample':1,
                                                                                  })

                    rows = self.ca.load_data( obj_id, data_file,
                                              use_kalman_smoothing=use_kalman_smoothing,
                                              frames_per_second=fps,
                                              dynamic_model_name=model,
                                              ) # load kalman data

                    # if rows are missing in original kalman data, we can interpolate here:

                    #print "len(results['X_kalmanized']),len(rows),obj_id",len(results['X_kalmanized']),len(rows),obj_id
                    assert len(results['X_kalmanized']) == len(rows)


    def test_CachingAnalyzer_load_data(self):
        for data_file,test_obj_ids,is_mat_file,fps,model in zip(self.data_files,
                                                                self.test_obj_ids_list,
                                                                self.is_mat_files,
                                                                self.fps,
                                                                self.dynamic_model,
                                                                ):
            #for use_kalman_smoothing in [True,False]:
            for use_kalman_smoothing in [False,True]:
                for obj_id in test_obj_ids:
                    rows = self.ca.load_data( obj_id, data_file,
                                              use_kalman_smoothing=use_kalman_smoothing,
                                              frames_per_second=fps,
                                              dynamic_model_name=model,
                                              ) # load kalman data
                    #print 'use_kalman_smoothing',use_kalman_smoothing
                    test_obj_ids = obj_id*numpy.ones_like(rows['obj_id'])
                    #print "rows['obj_id'], test_obj_ids",rows['obj_id'], test_obj_ids
                    assert numpy.allclose( rows['obj_id'], test_obj_ids )
                    #print

class TestChooseOrientations(unittest.TestCase):
    def test_choose_orientations(self):
        x = numpy.linspace(0,1000,10)
        y = numpy.ones_like(x)
        z = numpy.ones_like(x)
        rows = np.recarray( x.shape, dtype=[('x',np.float),
                                            ('y',np.float),
                                            ('z',np.float)])
        rows['x']=x; rows['y']=y; rows['z']=z
        directions = np.zeros((len(x),3))
        directions[:,0] = np.random.randn( len(x) )

        mag = np.sqrt(np.sum(directions**2,axis=1))
        directions = directions/mag[:,np.newaxis]
        #print directions
        new_dir = choose_orientations(rows,directions,frames_per_second=1,
                                      elevation_up_bias_degrees=0)
        assert new_dir.shape == directions.shape
        assert np.alltrue(~np.isnan(new_dir))
