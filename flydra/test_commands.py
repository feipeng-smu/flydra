"""test flydra installed system commands"""
import pkg_resources
import os, subprocess, tempfile, shutil
import numpy as np
import scipy.misc
from optparse import OptionParser
import nose

AUTOGEN_DIR = os.path.join(os.path.split(__file__)[0],'autogenerated')
GALLERY_PATH = os.path.join(os.path.split(__file__)[0],'..',
                            'flydra-sphinx-docs','gallery.rst')

DATAFILE2D = pkg_resources.resource_filename('flydra.a2','sample_datafile.h5')
DATAFILE3D = pkg_resources.resource_filename('flydra.a2','sample_datafile.h5')

def _get_names_dict(data2d,data3d):
    DATAFILE2D_NOEXT = os.path.splitext(data2d)[0]
    DATAFILE3D_NOEXT = os.path.splitext(data3d)[0]
    names = dict(DATAFILE2D=data2d,
                 DATAFILE3D=data3d,
                 DATAFILE2D_NOEXT=DATAFILE2D_NOEXT,
                 DATAFILE3D_NOEXT=DATAFILE3D_NOEXT,
                 )
    return names

CANNONICAL_FILENAMES = {'DATAFILE2D':'DATAFILE2D.h5',
                        'DATAFILE3D':'DATAFILE3D.h5',
                        'target':'image.png'}

# image based commands
image_info = [
    {'cmd':('flydra_analysis_plot_kalman_2d %(DATAFILE2D)s '
            '--save-fig=%(target)s'),
     'result':'plot_kalman_2d.png',
     'title':'Camera view of 2D data',
     },

    {'cmd':('flydra_analysis_plot_timeseries_2d_3d %(DATAFILE2D)s '
            '--save-fig=%(target)s'),
     'result':'plot_timeseries_2d.png',
     'title':'Timeseries of 2D data',
     },

    {'cmd':('flydra_analysis_plot_timeseries_2d_3d %(DATAFILE2D)s '
            '--kalman-file=%(DATAFILE3D)s --disable-kalman-smoothing '
            '--save-fig=%(target)s'),
     'result':'plot_timeseries_2d_3d.png',
     'title':'Timeseries of 2D data with overlaid 3D tracking data',
     },

    ]

# non-image based commands
command_info =  [
    {'cmd':'data2smoothed %(DATAFILE3D)s --time-data=%(DATAFILE2D)s',
     'outfile':'%(DATAFILE3D_NOEXT)s_smoothed.mat',
     'result':'data2smoothed.mat',
     'rst_comments':"""This produces a .mat file named
``%(outfile)s``. This file contains smoothed tracking data in addition
to (unsmoothed) maximum likelihood position estimates."""
     }, ]


gallery_rst_src = """
Gallery
*******

This page shows images that were automatically generated by the
command line tools installed with flydra. The command line used to
generate each figure is shown. These figures also serve as unit tests
for flydra -- the stored versions are compared with newly generated
versions whenever nosetests_ is run.

.. _nosetests: http://somethingaboutorange.com/mrl/projects/nose/

.. This file generated by flydra_test_commands --generate. EDITS WILL BE LOST.

Image gallery
=============

%(image_gallery)s

Command gallery
===============

%(command_gallery)s

"""

def test_image_generating_commands():
    for info in image_info:
        yield check_command_with_image, 'check', info

def test_commands():
    for info in command_info:
        yield check_command, 'check', info

def generate_images():
    image_gallery = ''
    for info in image_info:
        check_command_with_image( 'generate', info)
        cmd_show = info['cmd']%CANNONICAL_FILENAMES
        names = _get_names_dict(CANNONICAL_FILENAMES['DATAFILE2D'],
                                CANNONICAL_FILENAMES['DATAFILE3D'])
        if 'title' in info:
            title = info['title']
        else:
            title = info['cmd'].split()[0]
        image_gallery += title+'\n'
        image_gallery += '.'*len(title)+'\n'
        image_gallery += '\n'
        image_gallery += 'The following command generated this image::\n\n'
        image_gallery += '  '+cmd_show+'\n\n'
        if 'rst_comments' in info:
            image_gallery += info['rst_comments']%names + '\n'
        image_gallery += """
.. image:: ../flydra/autogenerated/%(result)s
  :width: %(width)d
"""%{'result':info['result'],'width':600}
        image_gallery += '\n'

    return image_gallery

def generate_commands():
    command_gallery = ''
    for info in command_info:
        check_command( 'generate', info )
        cmd_show = info['cmd']%CANNONICAL_FILENAMES
        names = _get_names_dict(CANNONICAL_FILENAMES['DATAFILE2D'],
                                CANNONICAL_FILENAMES['DATAFILE3D'])
        if 'outfile' in info:
            names['outfile'] = info['outfile']%names

        if 'title' in info:
            title = info['title']
        else:
            title = info['cmd'].split()[0]
        command_gallery += title+'\n'
        command_gallery += '.'*len(title)+'\n'
        command_gallery += '\n'
        command_gallery += '::\n\n'
        command_gallery += '  '+cmd_show+'\n\n'
        if 'rst_comments' in info:
            command_gallery += info['rst_comments']%names + '\n'
        command_gallery += '\n'
    return command_gallery

def generate():
    image_gallery = generate_images()
    command_gallery = generate_commands()

    gallery_rst = gallery_rst_src%{'image_gallery':image_gallery,
                                   'command_gallery':command_gallery}
    fd = open(GALLERY_PATH,mode='w')
    fd.write(gallery_rst)
    fd.close()

def check_command_with_image(mode,info):
    assert mode in ['check','generate']
    result_fullpath = os.path.join( AUTOGEN_DIR, info['result'] )
    if mode=='check':
        handle, target = tempfile.mkstemp('.png')
    elif mode=='generate':
        target = result_fullpath
    names = _get_names_dict(DATAFILE2D,DATAFILE3D)
    names['target']=target

    cmd = info['cmd']%names
    subprocess.check_call(cmd, shell=True)
    if mode=='check':
        are_close = are_images_close( target, result_fullpath )
        os.unlink(target)
        assert are_close == True

def check_command(mode,info):
    assert mode in ['check','generate']
    result_fullpath = os.path.join( AUTOGEN_DIR, info['result'] )
    names = _get_names_dict(DATAFILE2D,DATAFILE3D)

    cmd = info['cmd']%names

    # 'outfile' key indicates that we don't have control of location
    # of output file -- we must accept where command will put it.

    if 'outfile' in info:
        target = info['outfile']%names
        if os.path.exists(target):
            raise RuntimeError('target %s already exists'%target)
    elif 0:
        # not yet needed
        suffix = info.get('suffix','')
        handle, target = tempfile.mkstemp(suffix)

    subprocess.check_call(cmd, shell=True)

    if mode=='check':
        are_close = are_files_close( target, result_fullpath )
        os.unlink(target)
        assert are_close == True
    elif mode=='generate':
        shutil.move( target, result_fullpath )

def are_files_close(filename1, filename2):
    fd1 = open(filename1)
    fd2 = open(filename2)
    are_close = True
    while 1:
        buf1 = fd1.read(1024*1024*8)
        buf2 = fd2.read(1024*1024*8)
        if not buf1 == buf2:
            are_close = False
            break
        if len(buf1)==0:
            break
    return are_close

def are_images_close( im1_filename, im2_filename):
    """return True if two image files are very similar"""
    im1 = scipy.misc.pilutil.imread(im1_filename)
    im2 = scipy.misc.pilutil.imread(im2_filename)
    if im1.ndim != im2.ndim:
        raise ValueError('images have different ndim')
    if im1.shape != im2.shape:
        raise ValueError('images have different shape')
    return np.allclose( im1, im2 )

def main():
    usage = '%prog FILE [options]'

    parser = OptionParser(usage)
    parser.add_option("--generate", action='store_true',
                      default=False)
    (options, args) = parser.parse_args()
    if options.generate:
        generate()
    else:
        nose.main() # how to limit to just this module?

if __name__=='__main__':
    main()
