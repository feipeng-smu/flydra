import numpy
import math

def _get_A_C_arrays(dt=None):
    """get linear dynamical system matrices A and C

    dt is the time-step in seconds
    """
    # distance units are in m
    # time units are in sec
    # thus, velocity is (m/sec)

    ss = 9 # length of state vector (state size)
    os = 3 # length of observation vector (observation size)

    half_dt2 = 0.5*dt**2
    ad = 0.1 # acceleration decay

    # state vector describes a particle in brownian motion
    # [ x y z xvel yvel zvel xaccel yaccel zaccel]

    # process update matrix (time evolution update matrix)
    A = numpy.array([[   1. ,    0. ,    0. ,   dt  ,    0. ,    0. , half_dt2 ,   0.     ,    0. ],
                     [   0. ,    1. ,    0. ,    0. ,   dt  ,    0. ,   0.     , half_dt2 ,    0. ],
                     [   0. ,    0. ,    1. ,    0. ,    0. ,   dt  ,   0.     ,   0.     ,  half_dt2  ],
                     [   0. ,    0. ,    0. ,    1. ,    0. ,    0. ,  dt      ,   0.     ,    0. ],
                     [   0. ,    0. ,    0. ,    0. ,    1. ,    0. ,   0.     ,  dt      ,    0. ],
                     [   0. ,    0. ,    0. ,    0. ,    0. ,    1. ,   0.     ,   0.     ,   dt  ],
                     [   0. ,    0. ,    0. ,    0. ,    0. ,    0. ,   ad     ,   0.     ,    0. ],
                     [   0. ,    0. ,    0. ,    0. ,    0. ,    0. ,   0.     ,   ad     ,    0. ],
                     [   0. ,    0. ,    0. ,    0. ,    0. ,    0. ,   0.     ,   0.     ,    ad]])
    A_model_name = 'fixed_accel'

    # measurement prediction matrix
    C = numpy.zeros((os,ss))
    C[:os,:os] = numpy.eye(os) # directly measure x,y,z positions

    ### process covariance
    ##Q = numpy.zeros((ss,ss))
    ##for i in range(6,9):
    ##    Q[i,i] = 10.0 # acceleration noise (near (3.16m*sec**-2)**2)

    ### measurement noise covariance matrix
    ##R = 1e-6*numpy.eye(os) # (1mm)**2 = (0.001m)**2
    model = {'A':A,
             'A_model_name':A_model_name,
             'C':C,
             'ss':ss,
             'os':os,
             'dt':dt,
             }
    return model

def get_dynamic_model_dict(*args,**kw):
    import warnings
    warnings.warn('DeprecationWarning: call create_dynamic_model_dict(), not old get_dynamic_model_dict')
    return create_dynamic_model_dict(*args,**kw)

def create_dynamic_model_dict(dt=None):
    """get linear dynamical system matrices

    dt is the time-step in seconds
    """
    base_model_dict = _get_A_C_arrays(dt)

    ss = 9 # length of state vector (state size)
    os = 3 # length of observation vector (observation size)

    dynamic_models = {}

    ######################################
    # 'hbird3, units: mm':
    # process covariance
    Q = numpy.zeros((ss,ss))
    for i in range(0,3):
        #Q[i,i] = (0.005)**2
        Q[i,i] = (0.010)**2

    for i in range(3,6):
        Q[i,i] = (.5)**2 # velocity noise

    for i in range(6,9):
        Q[i,i] = 10.0 # acceleration noise (near (3.16m*sec**-2)**2)
        #Q[i,i] = 50.0

    # measurement noise covariance matrix
    #R = 1e-6*numpy.eye(os) # (1mm)**2 = (0.001m)**2
    #R = 1e-4*numpy.eye(os) # (10mm)**2 = (0.01m)**2
    #R = 2e-4*numpy.eye(os)
    R = 2.5e-3*numpy.eye(os) # (50mm)**2 = (0.05m)**2
    #R = 2.5e-2*numpy.eye(os)

    newdict = dict(
        # these 2 values are old and could probably be improved:
        min_dist_to_believe_new_meters=0.0,
        min_dist_to_believe_new_sigma=9.0,

        n_sigma_accept=2.8,
        #n_sigma_accept=2.4,
        max_variance_dist_meters=math.sqrt(0.06),
        initial_position_covariance_estimate=(0.1)**2, # 30mm2
        #initial_acceleration_covariance_estimate=15,
        initial_velocity_covariance_estimate=50,
        initial_acceleration_covariance_estimate=150,
        Q=Q,
        R=R)
    newdict.update(base_model_dict)
    dynamic_models['hummingbird dynamics, units: mm'] = newdict
    ######################################

    # 'fly dynamics, high precision calibration, units: mm':
    # process covariance
    Q = numpy.zeros((ss,ss))
    for i in range(0,3):
        Q[i,i] = (0.001)**2
    for i in range(3,6):
        Q[i,i] = (0.2)**2
    for i in range(6,9):
        Q[i,i] = 10.0 # acceleration noise (near (3.16m*sec**-2)**2)

    # measurement noise covariance matrix
    R = 1e-6*numpy.eye(os)

    newdict = dict(
        min_dist_to_believe_new_meters=0.01, # 1 cm
        min_dist_to_believe_new_sigma=3.0,
        n_sigma_accept=9.0,
        max_variance_dist_meters=0.02,
        initial_position_covariance_estimate=1e-6,
        initial_acceleration_covariance_estimate=15,
        Q=Q,
        R=R)
    newdict.update(base_model_dict)
    dynamic_models['fly dynamics, high precision calibration, units: mm'] = newdict

    ## ##################################################

    return dynamic_models
