#!/usr/bin/env python

# --------------------------------------------------------
# Faster R-CNN
# Copyright (c) 2015 Microsoft
# Licensed under The MIT License [see LICENSE for details]
# Written by Ross Girshick
# --------------------------------------------------------

"""
Demo script showing detections in sample images.

See README.md for installation instructions before running.
"""

import _init_paths
from fast_rcnn.config import cfg
from fast_rcnn.test import im_detect
from fast_rcnn.nms_wrapper import nms
from utils.timer import Timer
import matplotlib.pyplot as plt
import numpy as np
import scipy.io as sio
import caffe, os, sys, cv2
import argparse

import rospy
from ros_faster_rcnn.msg import *
from sensor_msgs.msg import CompressedImage
from cv_bridge import CvBridge, CvBridgeError

RUNNING = False
IMAGE = CompressedImage()
	
def detect(image):
	"""Detect object classes in an image using pre-computed object proposals."""
	global NET
	
	# Detect all object classes and regress object bounds
	# rospy.loginfo("Starting detection")
	timer = Timer()
	timer.tic()
	scores, boxes = im_detect(NET, image)
	timer.toc()
	# rospy.loginfo('Detection took %f seconds for %d object proposals', timer.total_time, boxes.shape[0])
	return (scores, boxes)
			
def imageCallback(im):
	global IMAGE
	global RUNNING
	# rospy.loginfo('Image received')
	if (RUNNING):
		# rospy.logwarn('Detection already running, message omitted')
		rospy.logdebug('Detection already running, message omitted')
	else:
		RUNNING = True
		IMAGE = im

def parse_args():
	"""Parse input arguments."""
	# Filter roslaunch arguments
	sys.argv = filter(lambda arg: not arg.startswith('__'), sys.argv)
	sys.argc = len(sys.argv)
	
	# Parse the other arguments
	parser = argparse.ArgumentParser(description='Faster R-CNN demo')
	parser.add_argument('--gpu', dest='gpu_id', help='GPU device id to use [0]',
						default=0, type=int)
	parser.add_argument('--cpu', dest='cpu_mode',
						help='Use CPU mode (overrides --gpu)',
						action='store_true')
	parser.add_argument('--tresh', dest='treshold', help='The treshold for the detection', 
						default=0.5, type=float)
	parser.add_argument('--prototxt', dest='prototxt', help='The proto file', 
						default='../libraries/py-faster-rcnn/models/pascal_voc/VGG16/faster_rcnn_alt_opt/faster_rcnn_test.pt')
	parser.add_argument('--model', dest='model', help='The model file', 
						default='../libraries/py-faster-rcnn/data/faster_rcnn_models/VGG16_faster_rcnn_final.caffemodel')
	parser.add_argument('--classes', dest='classes', help='The file containing the classes', 
						default='classes.txt')
	parser.add_argument('--cameraSubscriber', dest='cameraSubscriber', help='The Subscriber camera node', 
						default='/camera/rgb/image_raw')
	parser.add_argument('--imageWindow', dest='imageWindow', help='image window name', 
						default='Image window')
	args = parser.parse_args()
	
	return args
    
def parseClasses(classFile):
	with open(classFile) as f:
		content = f.readlines()
	return ['__background__'] + map(lambda x: x[:-1], content)

def generateDetections (scores, boxes, classes, threshold):
	# Visualize detections for each class
	NMS_THRESH = 0.3	
	res = []
	global bbox
	global score
	for cls_ind, cls in enumerate(classes[1:]):
		cls_ind += 1 # because we skipped background
		cls_boxes = boxes[:, 4*cls_ind:4*(cls_ind + 1)]
		cls_scores = scores[:, cls_ind]
		dets = np.hstack((cls_boxes, cls_scores[:, np.newaxis])).astype(np.float32)
		keep = nms(dets, NMS_THRESH)
		dets = dets[keep, :]

		inds = np.where(dets[:, -1] >= threshold)[0]

		for i in inds:
			bbox = dets[i, :4]
			score = dets[i, -1]
			
			msg = Detection()
			msg.header.frame_id = args.cameraSubscriber
			msg.x = bbox[0]
			msg.y = bbox[1]
			msg.width =  bbox[2] - bbox[0]
			msg.height = bbox[3] - bbox[1]
			msg.object_class = classes[cls_ind]
			msg.p = score
			res.append(msg)
	
	return res
	
def getResultImage (detections, image):
	font = cv2.FONT_HERSHEY_SIMPLEX
	textSize = cv2.getTextSize("test", font, 1, 2)
	delta = (textSize[1] * .3, textSize[1] * 2.4)
		
	for det in detections:
		cv2.rectangle(image, (det.x, det.y), (det.x + det.width, det.y + det.height), (0, 0, 255), 2)
		text = "{}: p={:.2f}".format(det.object_class, det.p)
		cv2.putText(image, text, (int(det.x + delta[0]), int(det.y + delta[1])), font, 0.8, (0, 0, 255), 2)
	return image
	
if __name__ == '__main__':
	cfg.TEST.HAS_RPN = True  # Use RPN for proposals

	args = parse_args()

	pub_single = rospy.Publisher('rcnn/res/single', Detection, queue_size = 10)
	pub_array = rospy.Publisher('rcnn/res/array', DetectionArray, queue_size = 2)
	pub_full = rospy.Publisher('rcnn/res/full', DetectionFull, queue_size = 2)
	
	rospy.init_node('simpleDetect')
	# sub_image = rospy.Subscriber("rcnn/image_raw", Image, imageCallback)
	# sub_image = rospy.Subscriber("/camera/rgb/image_rect_color", Image, imageCallback)
	# sub_image = rospy.Subscriber(args.cameraSubscriber, Image, imageCallback)
	sub_image = rospy.Subscriber(args.cameraSubscriber, CompressedImage, imageCallback)

	prototxt = os.path.join(os.path.dirname(__file__), args.prototxt)
	caffemodel = os.path.join(os.path.dirname(__file__), args.model)
	classes = parseClasses(os.path.join(os.path.dirname(__file__), args.classes))

	if not os.path.isfile(caffemodel):
		rospy.logerr('%s not found.\nDid you run ./data/script/fetch_faster_rcnn_models.sh?', caffemodel)

	if args.cpu_mode:
		caffe.set_mode_cpu()
	else:
		caffe.set_mode_gpu()
		caffe.set_device(args.gpu_id)
		cfg.GPU_ID = args.gpu_id
	NET = caffe.Net(prototxt, caffemodel, caffe.TEST)

	rospy.loginfo('Loaded network %s', caffemodel)
	rospy.loginfo('Running detection with these classes: %s', str(classes))
	rospy.loginfo('Warmup started')
	im = 128 * np.ones((300, 500, 3), dtype=np.uint8)
	timer = Timer()
	timer.tic()
	for i in xrange(2):
		_, _= im_detect(NET, im)
	timer.toc()
	rospy.loginfo('Warmup done in %f seconds. Starting node', timer.total_time)
	
	rate = rospy.Rate(30)
	bridge = CvBridge()
	while not rospy.is_shutdown():
		if (RUNNING):
			rate.sleep()
			# cv_image = bridge.imgmsg_to_cv2(IMAGE)
			cv_image = bridge.compressed_imgmsg_to_cv2(IMAGE)
			(scores, boxes) = detect(cv_image)
			detections = generateDetections(scores, boxes, classes, args.treshold)

			
			for det in detections:
				rospy.loginfo(' [%s] detected, score: %.2f', det.object_class, det.p)
				rospy.loginfo(' Rectangle: (%d, %d), (%d, %d)', det.x, det.y, det.x + det.width, det.y + det.height)
			
			cv2.imshow(args.imageWindow, getResultImage(detections, cv_image))
			cv2.waitKey(3)
			
			if (pub_single.get_num_connections() > 0):
				for msg in detections:
					pub_single.publish(msg)
					
			if (pub_array.get_num_connections() > 0 or pub_full.get_num_connections() > 0):
				array = DetectionArray()
				array.size = len(detections)
				array.data = detections
				
				if (pub_full.get_num_connections() > 0):
					msg = DetectionFull()
					msg.detections = array
					msg.image =  bridge.cv2_to_imgmsg(getResultImage(detections, bridge.imgmsg_to_cv2(IMAGE)))
					pub_full.publish(msg)
				else :
					pub_array.publish(array)
			
			# (rows,cols,channels) = cv_image.shape
			# cv2.rectangle(cv_image, (int(bbox[0]),int(bbox[1])), (int(bbox[2]),int(bbox[3])), (0,0,255), 2) 
			# cv2.imshow("Image window", cv_image)
			# cv2.waitKey(3)

			RUNNING = False
		else:
			rate.sleep()
