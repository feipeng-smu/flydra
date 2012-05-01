## *********************************************************
## 
## File autogenerated for the camnode package 
## by the dynamic_reconfigure package.
## Please do not edit.
## 
## ********************************************************/

##**********************************************************
## Software License Agreement (BSD License)
##
##  Copyright (c) 2008, Willow Garage, Inc.
##  All rights reserved.
##
##  Redistribution and use in source and binary forms, with or without
##  modification, are permitted provided that the following conditions
##  are met:
##
##   * Redistributions of source code must retain the above copyright
##     notice, this list of conditions and the following disclaimer.
##   * Redistributions in binary form must reproduce the above
##     copyright notice, this list of conditions and the following
##     disclaimer in the documentation and/or other materials provided
##     with the distribution.
##   * Neither the name of the Willow Garage nor the names of its
##     contributors may be used to endorse or promote products derived
##     from this software without specific prior written permission.
##
##  THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
##  "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
##  LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
##  FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
##  COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
##  INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
##  BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
##  LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
##  CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
##  LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
##  ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
##  POSSIBILITY OF SUCH DAMAGE.
##**********************************************************/

config_description = [{'srcline': 9, 'description': 'Brightness', 'max': 255, 'cconsttype': 'const int', 'ctype': 'int', 'srcfile': '../cfg/camnode.cfg', 'name': 'brightness', 'edit_method': '', 'default': 0, 'level': 0, 'min': 0, 'type': 'int'}, {'srcline': 10, 'description': 'Percent multiplication on pixel values', 'max': 740, 'cconsttype': 'const int', 'ctype': 'int', 'srcfile': '../cfg/camnode.cfg', 'name': 'gain', 'edit_method': '', 'default': 100, 'level': 0, 'min': 0, 'type': 'int'}, {'srcline': 11, 'description': 'Exposure time in microseconds', 'max': 4095, 'cconsttype': 'const int', 'ctype': 'int', 'srcfile': '../cfg/camnode.cfg', 'name': 'shutter', 'edit_method': '', 'default': 100, 'level': 0, 'min': 0, 'type': 'int'}, {'srcline': 13, 'description': 'Trigger framerate', 'max': 200.0, 'cconsttype': 'const double', 'ctype': 'double', 'srcfile': '../cfg/camnode.cfg', 'name': 'framerate_trigger', 'edit_method': '', 'default': 20.0, 'level': 0, 'min': 0.0, 'type': 'double'}, {'srcline': 14, 'description': 'Maximum framerate', 'max': 200.0, 'cconsttype': 'const double', 'ctype': 'double', 'srcfile': '../cfg/camnode.cfg', 'name': 'framerate_max', 'edit_method': '', 'default': 20.0, 'level': 0, 'min': 0.0, 'type': 'double'}, {'srcline': 15, 'description': 'Threshold for absdiff', 'max': 10.0, 'cconsttype': 'const double', 'ctype': 'double', 'srcfile': '../cfg/camnode.cfg', 'name': 'threshold_diff', 'edit_method': '', 'default': 5.0, 'level': 0, 'min': 0.0, 'type': 'double'}, {'srcline': 16, 'description': 'Threshold for clear', 'max': 10.0, 'cconsttype': 'const double', 'ctype': 'double', 'srcfile': '../cfg/camnode.cfg', 'name': 'threshold_clear', 'edit_method': '', 'default': 0.3, 'level': 0, 'min': 0.0, 'type': 'double'}, {'srcline': 18, 'description': 'Criterion to determine if a pixel is significantly different than the mean', 'max': 20.0, 'cconsttype': 'const double', 'ctype': 'double', 'srcfile': '../cfg/camnode.cfg', 'name': 'n_sigma', 'edit_method': '', 'default': 7.0, 'level': 0, 'min': 0.0, 'type': 'double'}, {'srcline': 19, 'description': 'Number of erosions', 'max': 20, 'cconsttype': 'const int', 'ctype': 'int', 'srcfile': '../cfg/camnode.cfg', 'name': 'n_erode', 'edit_method': '', 'default': 0, 'level': 0, 'min': 0, 'type': 'int'}, {'srcline': 21, 'description': 'ROI left', 'max': 1920, 'cconsttype': 'const int', 'ctype': 'int', 'srcfile': '../cfg/camnode.cfg', 'name': 'roi/left', 'edit_method': '', 'default': 0, 'level': 0, 'min': 0, 'type': 'int'}, {'srcline': 22, 'description': 'ROI top', 'max': 1080, 'cconsttype': 'const int', 'ctype': 'int', 'srcfile': '../cfg/camnode.cfg', 'name': 'roi/top', 'edit_method': '', 'default': 0, 'level': 0, 'min': 0, 'type': 'int'}, {'srcline': 23, 'description': 'ROI right', 'max': 1920, 'cconsttype': 'const int', 'ctype': 'int', 'srcfile': '../cfg/camnode.cfg', 'name': 'roi/right', 'edit_method': '', 'default': 1023, 'level': 0, 'min': 0, 'type': 'int'}, {'srcline': 24, 'description': 'ROI bottom', 'max': 1080, 'cconsttype': 'const int', 'ctype': 'int', 'srcfile': '../cfg/camnode.cfg', 'name': 'roi/bottom', 'edit_method': '', 'default': 767, 'level': 0, 'min': 0, 'type': 'int'}, {'srcline': 25, 'description': 'Trigger mode', 'max': 10, 'cconsttype': 'const int', 'ctype': 'int', 'srcfile': '../cfg/camnode.cfg', 'name': 'trigger_mode', 'edit_method': '', 'default': 0, 'level': 0, 'min': 0, 'type': 'int'}, {'srcline': 27, 'description': 'Moving Average Background', 'max': True, 'cconsttype': 'const bool', 'ctype': 'bool', 'srcfile': '../cfg/camnode.cfg', 'name': 'dynamic_background', 'edit_method': '', 'default': True, 'level': 0, 'min': False, 'type': 'bool'}, {'srcline': 28, 'description': 'Use cmp', 'max': True, 'cconsttype': 'const bool', 'ctype': 'bool', 'srcfile': '../cfg/camnode.cfg', 'name': 'use_cmp', 'edit_method': '', 'default': False, 'level': 0, 'min': False, 'type': 'bool'}, {'srcline': 30, 'description': 'Convert pixels to red (requires color cameras)', 'max': True, 'cconsttype': 'const bool', 'ctype': 'bool', 'srcfile': '../cfg/camnode.cfg', 'name': 'use_color_filter', 'edit_method': '', 'default': False, 'level': 0, 'min': False, 'type': 'bool'}, {'srcline': 31, 'description': 'Color filter 1', 'max': 255, 'cconsttype': 'const int', 'ctype': 'int', 'srcfile': '../cfg/camnode.cfg', 'name': 'color_filter_1', 'edit_method': '', 'default': 0, 'level': 0, 'min': 0, 'type': 'int'}, {'srcline': 32, 'description': 'Color filter 2', 'max': 255, 'cconsttype': 'const int', 'ctype': 'int', 'srcfile': '../cfg/camnode.cfg', 'name': 'color_filter_2', 'edit_method': '', 'default': 150, 'level': 0, 'min': 0, 'type': 'int'}, {'srcline': 33, 'description': 'Color filter 3', 'max': 255, 'cconsttype': 'const int', 'ctype': 'int', 'srcfile': '../cfg/camnode.cfg', 'name': 'color_filter_3', 'edit_method': '', 'default': 255, 'level': 0, 'min': 0, 'type': 'int'}, {'srcline': 34, 'description': 'Color filter saturation', 'max': 255, 'cconsttype': 'const int', 'ctype': 'int', 'srcfile': '../cfg/camnode.cfg', 'name': 'color_filter_sat', 'edit_method': '', 'default': 100, 'level': 0, 'min': 0, 'type': 'int'}]

min = {}
max = {}
defaults = {}
level = {}
type = {}
all_level = 0

for param in config_description:
    min[param['name']] = param['min']
    max[param['name']] = param['max']
    defaults[param['name']] = param['default']
    level[param['name']] = param['level']
    type[param['name']] = param['type']
    all_level = all_level | param['level']

