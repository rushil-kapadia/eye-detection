# tobiiglassescontroller.py: A Python controller for Tobii Pro Glasses 2
#
# Copyright (C) 2019  Davide De Tommaso
#
#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version
#
#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.
#
#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <https://www.gnu.org/licenses/>

import json
import time
import datetime
import threading
import socket
import uuid
import logging
import struct
import sys
import select

# python2 backwards compatibility for errors
if sys.version_info[0] < 3:
	class ConnectionError(BaseException):
		pass

try:
	import netifaces
	TOBII_DISCOVERY_ALLOWED = True
except:
	TOBII_DISCOVERY_ALLOWED = False

try:
	from urllib.parse import urlparse, urlencode
	from urllib.request import urlopen, Request
	from urllib.error import URLError, HTTPError
except ImportError:
	from urlparse import urlparse
	from urllib import urlencode
	from urllib2 import urlopen, Request, HTTPError, URLError

socket.IPPROTO_IPV6 = 41
TOBII_DATETIME_FORMAT = '%Y-%m-%dT%H:%M:%S+%f'
TOBII_DATETIME_FORMAT_HUMREAD = '%d/%m/%Y %H:%M:%S'

class TobiiGlassesController():

	def __init__(self, address = None, video_scene = False, timeout = None):
		self.timeout = 1
		self.streaming = False
		self.video_scene = video_scene
		self.udpport = 49152
		self.address = address
		self.iface_name = None
		logging.basicConfig(format='[%(levelname)s]: %(message)s', level=logging.DEBUG)

		self.data = {}
		nd = {'ts': -1}
		self.data['mems'] = { 'ac': nd, 'gy': nd }
		self.data['right_eye'] = { 'pc': nd, 'pd': nd, 'gd': nd}
		self.data['left_eye'] = { 'pc': nd, 'pd': nd, 'gd': nd}
		self.data['gp'] = nd
		self.data['gp3'] = nd
		self.data['pts'] = nd
		self.data['vts'] = nd

		self.project_id = str(uuid.uuid4())
		self.project_name = "TobiiProGlasses PyController"
		self.recn = 0

		self.KA_DATA_MSG = "{\"type\": \"live.data.unicast\", \"key\": \""+ str(uuid.uuid4()) +"\", \"op\": \"start\"}"
		self.KA_VIDEO_MSG = "{\"type\": \"live.video.unicast\",\"key\": \""+ str(uuid.uuid4()) +"_video\",  \"op\": \"start\"}"

		if self.address is None:
			data, address = self.__discover_device__()
			if address is None:
				raise ConnectionError("No device found using discovery process")
			else:
				try:
					self.address = data["ipv4"]
				except:
					self.address = address
		if "%" in self.address:
			if sys.platform == "win32":
				self.address,self.iface_name = self.address.split("%")
			else:
				self.iface_name = self.address.split("%")[1]
		self.__set_URL__(self.udpport, self.address)
		if self.__connect__(timeout = timeout) is False:
			raise ConnectionError("Failed to connect to Tobii device")

	def __del__(self):
		self.close()

	def __connect__(self, timeout = None):
		logging.debug("Connecting to the Tobii Pro Glasses 2 ...")
		self.data_socket = self.__mksock__()
		if self.video_scene:
			self.video_socket = self.__mksock__()
		res = self.wait_until_status_is_ok(timeout=timeout)
		if res is True:
			logging.debug("Tobii Pro Glasses 2 successful connected!")
		else:
			logging.error("An error occurs trying to connect to the Tobii Pro Glasses")
		return res

	def __disconnect__(self):
		logging.debug("Disconnecting to the Tobii Pro Glasses 2")
		self.data_socket.close()
		if self.video_scene:
			self.video_socket.close()
		logging.debug("Tobii Pro Glasses 2 successful disconnected!")
		return True

	def __discover_device__(self):
		if TOBII_DISCOVERY_ALLOWED == False:
			logging.error("Device discovery is not available due to a missing dependency (netifaces)")
			exit(1)

		logging.debug("Looking for a Tobii Pro Glasses 2 device ...")
		MULTICAST_ADDR = 'ff02::1'
		PORT = 13006

		for i in netifaces.interfaces():
			if netifaces.AF_INET6 in netifaces.ifaddresses(i).keys():
				if "%" in netifaces.ifaddresses(i)[netifaces.AF_INET6][0]['addr']:
					if_name = netifaces.ifaddresses(i)[netifaces.AF_INET6][0]['addr'].split("%")[1]
					if_idx = socket.getaddrinfo(MULTICAST_ADDR + "%" + if_name, PORT, socket.AF_INET6, socket.SOCK_DGRAM)[0][4][3]
					s6 = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
					s6.settimeout(30.0)
					s6.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_IF, if_idx)
					s6.bind(('::', PORT))
					PORT_OUT = PORT if sys.platform == 'win32' or sys.platform == 'darwin' else PORT + 1
					try:
						discover_json = '{"type":"discover"}'
						s6.sendto(discover_json.encode('utf-8'), (MULTICAST_ADDR, PORT_OUT))
						logging.debug("Discover request sent to %s on interface %s " % ( str((MULTICAST_ADDR, PORT_OUT)),if_name) )
						logging.debug("Waiting for a reponse from the device ...")
						data, address = s6.recvfrom(1024)
						jdata = json.loads(data.decode('utf-8'))
						logging.debug("From: " + address[0] + " " + str(data))
						logging.debug("Tobii Pro Glasses found with address: [%s]" % address[0])
						return (jdata, address[0])
					except:
						logging.debug("No device found on interface %s" % if_name)

		logging.debug("The discovery process did not find any device!")
		return (None, None)

	def __get_current_datetime__(self, timeformat=TOBII_DATETIME_FORMAT):
		return datetime.datetime.now().replace(microsecond=0).strftime(timeformat)

	def __get_request__(self, api_action):
		url = self.base_url + api_action
		res = urlopen(url).read()
		data = json.loads(res.decode('utf-8'))
		return data

	def __grab_data__(self, socket):
		time.sleep(1)
		while self.streaming:
			try:
				data, address = socket.recvfrom(1024)
				jdata = json.loads(data.decode('utf-8'))
				self.__refresh_data__(jdata)
			except socket.timeout:
				logging.error("A timeout occurred while receiving data")
				self.streaming = False

	def __mksock__(self):
		iptype = socket.AF_INET
		if ':' in self.peer[0]:
			iptype = socket.AF_INET6
		res = socket.getaddrinfo(self.peer[0], self.peer[1], socket.AF_UNSPEC, socket.SOCK_DGRAM, 0, socket.AI_PASSIVE)
		family, socktype, proto, canonname, sockaddr = res[0]
		sock = socket.socket(family, socktype, proto)
		sock.settimeout(5.0)
		try:
			if iptype == socket.AF_INET6:
				sock.setsockopt(socket.SOL_SOCKET, 25, self.iface_name+'\0')
		except socket.error as e:
			if e.errno == 1:
				logging.warning("Binding to a network interface is permitted only for root users.")
		return sock

	def __post_request__(self, api_action, data=None, wait_for_response=True):
		url = self.base_url + api_action
		req = Request(url)
		req.add_header('Content-Type', 'application/json')
		data = json.dumps(data)
		logging.debug("Sending JSON: " + str(data))
		if wait_for_response is False:
			threading.Thread(target=urlopen, args=(req, data.encode('utf-8'),)).start()
			return None
		response = urlopen(req, data.encode('utf-8'))
		res = response.read()
		logging.debug("Response: " + str(res))
		try:
			res = json.loads(res.decode('utf-8'))
		except:
			pass
		return res

	def __refresh_data__(self, jsondata):
		try:
			gy = jsondata['gy']
			ts = jsondata['ts']
			if( (self.data['mems']['gy']['ts'] < ts) and (jsondata['s'] == 0) ):
				self.data['mems']['gy'] = jsondata
		except:
			pass
		try:
			ac = jsondata['ac']
			ts = jsondata['ts']
			if( (self.data['mems']['ac']['ts'] < ts) and (jsondata['s'] == 0) ):
				self.data['mems']['ac'] = jsondata
		except:
			pass
		try:
			pc = jsondata['pc']
			ts = jsondata['ts']
			eye = jsondata['eye']
			if( (self.data[eye + '_eye']['pc']['ts'] < ts) and (jsondata['s'] == 0) ):
				self.data[eye + '_eye']['pc'] = jsondata
		except:
			pass
		try:
			pd = jsondata['pd']
			ts = jsondata['ts']
			eye = jsondata['eye']
			if( (self.data[eye + '_eye']['pd']['ts'] < ts) and (jsondata['s'] == 0) ):
				self.data[eye + '_eye']['pd'] = jsondata
		except:
			pass
		try:
			gd = jsondata['gd']
			ts = jsondata['ts']
			eye = jsondata['eye']
			if( (self.data[eye + '_eye']['gd']['ts'] < ts) and (jsondata['s'] == 0) ):
				self.data[eye + '_eye']['gd'] = jsondata
		except:
			pass
		try:
			gp = jsondata['gp']
			ts = jsondata['ts']
			if( (self.data['gp']['ts'] < ts) and (jsondata['s'] == 0) ):
				self.data['gp'] = jsondata
		except:
			pass
		try:
			gp3 = jsondata['gp3']
			ts = jsondata['ts']
			if( (self.data['gp3']['ts'] < ts) and (jsondata['s'] == 0) ):
				self.data['gp3'] = jsondata
		except:
			pass
		try:
			pts = jsondata['pts']
			ts = jsondata['ts']
			if( (self.data['pts']['ts'] < ts) and (jsondata['s'] == 0) ):
				self.data['pts'] = jsondata
		except:
			pass
		try:
			vts = jsondata['vts']
			ts = jsondata['ts']
			if( (self.data['vts']['ts'] < ts) and (jsondata['s'] == 0) ):
				self.data['vts'] = jsondata
		except:
			pass
		try:
			pv = jsondata['pv']
			ts = jsondata['ts']
			if( (self.data['pv']['ts'] < ts) and (jsondata['s'] == 0) ):
				self.data['pv'] = jsondata
		except:
			pass

	def __send_keepalive_msg__(self, sock, msg):
		while self.streaming:
			res = sock.sendto(msg.encode('utf-8'), self.peer)
			time.sleep(self.timeout)

	def __set_URL__(self, udpport, address):
		if ':' in address:
			self.base_url = 'http://[%s]' % address
		else:
			self.base_url = 'http://' + address
		self.peer = (address, udpport)

	def __start_streaming__(self):
		self.streaming = True
		self.td = threading.Timer(0, self.__send_keepalive_msg__, [self.data_socket, self.KA_DATA_MSG])
		self.tg = threading.Timer(0, self.__grab_data__, [self.data_socket])
		if self.video_scene:
			self.tv = threading.Timer(0, self.__send_keepalive_msg__, [self.video_socket, self.KA_VIDEO_MSG])
			self.tv.start()
			logging.debug("Video streaming started...")
		self.td.start()
		self.tg.start()
		logging.debug("Data streaming started...")

	def close(self):
		if self.address is not None:
			if self.streaming:
				self.stop_streaming()
			self.__disconnect__()

	def create_calibration(self, project_id, participant_id):
		data = {'ca_project': project_id, 'ca_type': 'default',
				'ca_participant': participant_id,
				'ca_created': self.__get_current_datetime__()}
		json_data = self.__post_request__('/api/calibrations', data)
		logging.debug("Calibration " + json_data['ca_id'] + "created! Project: " + project_id + ", Participant: " + participant_id)
		return json_data['ca_id']

	def create_participant(self, project_id, participant_name = "DefaultUser", participant_notes = ""):
		participant_id = self.get_participant_id(participant_name)
		self.participant_name = participant_name

		if participant_id is None:
			data = {'pa_project': project_id,
					'pa_info': { 'EagleId': str(uuid.uuid5(uuid.NAMESPACE_DNS, self.participant_name)),
								 'Name': self.participant_name,
								 'Notes': participant_notes},
					'pa_created': self.__get_current_datetime__()}
			json_data = self.__post_request__('/api/participants', data)
			logging.debug("Participant " + json_data['pa_id'] + " created! Project " + project_id)
			return json_data['pa_id']
		else:
			logging.debug("Participant %s already exists ..." % participant_id)
			return participant_id

	def create_project(self, projectname = "DefaultProjectName"):
		project_id = self.get_project_id(projectname)

		if project_id is None:
			data = {'pr_info' : {'CreationDate': self.__get_current_datetime__(timeformat=TOBII_DATETIME_FORMAT_HUMREAD),
								 'EagleId':  str(uuid.uuid5(uuid.NAMESPACE_DNS, projectname)),
								 'Name': projectname},
					'pr_created': self.__get_current_datetime__() }
			json_data = self.__post_request__('/api/projects', data)
			logging.debug("Project %s created!" % json_data['pr_id'])
			return json_data['pr_id']
		else:
			logging.debug("Project %s already exists ..." % project_id)
			return project_id

	def create_recording(self, participant_id, recording_notes = ""):
		self.recn = self.recn + 1
		recording_name = "Recording_%s" % str(self.recn)
		data = {'rec_participant': participant_id,
				'rec_info': {'EagleId': str(uuid.uuid5(uuid.NAMESPACE_DNS, self.participant_name)),
							 'Name': recording_name,
							 'Notes': recording_notes},
							 'rec_created': self.__get_current_datetime__()}
		json_data = self.__post_request__('/api/recordings', data)
		return json_data['rec_id']

	def eject_sd(self):
		self.__get_request__('/api/eject')

	def get_battery_info(self):
		return ( "Battery info = [ Level: %.2f %% - Remaining Time: %.2f s ]" % (float(self.get_battery_level()), float(self.get_battery_remaining_time())) )

	def get_battery_level(self):
		return self.get_battery_status()['level']

	def get_battery_remaining_time(self):
		return self.get_battery_status()['remaining_time']

	def get_battery_status(self):
		return self.get_status()['sys_battery']

	def get_current_recording_id(self):
		return self.get_recording_status()['rec_id']

	def get_et_freq(self):
		return self.get_configuration()['sys_et_freq']

	def get_et_frequencies(self):
		return self.get_status()['sys_et']['frequencies']

	def get_participant_id(self, participant_name):
		participant_id = None
		participants = self.__get_request__('/api/participants')
		for participant in participants:
			try:
				if participant['pa_info']['Name'] == participant_name:
					participant_id = participant['pa_id']
			except:
				pass
		return participant_id

	def identify(self):
		self.__get_request__('/api/identify')

	def is_recording(self):
		rec_status = self.get_recording_status()
		if rec_status != {}:
			if rec_status['rec_state'] == "recording":
				return True
		return False

	def is_streaming(self):
		return self.streaming

	def get_address(self):
		return self.address

	def get_configuration(self):
		return self.__get_request__('/api/system/conf')

	def get_data(self):
		return self.data

	def get_participants(self):
		return self.__get_request__('/api/participants')

	def get_projects(self):
		return self.__get_request__('/api/projects')

	def get_project_id(self, project_name):
		project_id = None
		projects = self.__get_request__('/api/projects')
		for project in projects:
			try:
				if project['pr_info']['Name'] == project_name:
					project_id = project['pr_id']
			except:
				pass
		return project_id

	def get_recording_status(self):
		return self.get_status()['sys_recording']

	def get_recordings(self):
		return self.__get_request__('/api/recordings')

	def get_status(self):
		return self.__get_request__('/api/system/status')

	def get_storage_info(self):
		return ( "Storage info = [ Remaining Time: %.2f s ]" % float(self.get_battery_remaining_time()) )

	def get_storage_remaining_time(self):
		return self.get_storage_status()['remaining_time']

	def get_storage_status(self):
		return self.get_status()['sys_storage']

	def get_video_freq(self):
		return self.get_configuration()['sys_sc_fps']

	def pause_recording(self, recording_id):
		self.__post_request__('/api/recordings/' + recording_id + '/pause')
		return self.wait_for_recording_status(recording_id, ['paused']) == "paused"

	def send_custom_event(self, event_type, event_tag = ''):
		data = {'type': event_type, 'tag': event_tag}
		self.__post_request__('/api/events', data, wait_for_response=False)

	def send_experimental_var(self, variable_name, variable_value):
		self.send_custom_event('#%s#' % variable_name, variable_value)

	def send_experimental_vars(self, variable_names_list, variable_values_list):
		self.send_custom_event('@%s@' % str(variable_names_list), str(variable_values_list))

	def send_tobiipro_event(self, event_type, event_value):
		self.send_custom_event('JsonEvent', "{'event_type': '%s','event_value': '%s'}" % (event_type, event_value))

	def set_et_freq_50(self):
		data = {'sys_et_freq': 50}
		json_data = self.__post_request__('/api/system/conf', data)

	def set_et_freq_100(self):
		"""May not be available. Check get_et_frequencies() first."""
		data = {'sys_et_freq': 100}
		json_data = self.__post_request__('/api/system/conf', data)

	def set_et_indoor_preset(self):
		data = {'sys_sc_preset': 'Indoor'}
		json_data = self.__post_request__('/api/system/conf', data)

	def set_et_outdoor_preset(self):
		data = {'sys_ec_preset': 'ClearWeather'}
		json_data = self.__post_request__('/api/system/conf', data)

	def set_video_auto_preset(self):
		data = {'sys_sc_preset': 'Auto'}
		json_data = self.__post_request__('/api/system/conf', data)

	def set_video_gaze_preset(self):
		data = {'sys_sc_preset': 'GazeBasedExposure'}
		json_data = self.__post_request__('/api/system/conf', data)

	def set_video_freq_25(self):
		data = {'sys_sc_fps': 25}
		json_data = self.__post_request__('/api/system/conf/', data)

	def set_video_freq_50(self):
		data = {'sys_sc_fps': 50}
		json_data = self.__post_request__('/api/system/conf/', data)

	def start_calibration(self, calibration_id):
		self.__post_request__('/api/calibrations/' + calibration_id + '/start')

	def start_recording(self, recording_id):
		self.__post_request__('/api/recordings/' + recording_id + '/start')
		if self.wait_for_recording_status(recording_id, ['recording']) == "recording":
			return True
		return False

	def start_streaming(self):
		logging.debug("Start streaming ...")
		try:
			self.__start_streaming__()
		except:
			logging.error("An error occurs trying to connect to the Tobii Pro Glasses")

	def stop_recording(self, recording_id):
		self.__post_request__('/api/recordings/' + recording_id + '/stop')
		return self.wait_for_recording_status(recording_id, ['done']) == "done"

	def stop_streaming(self):
		logging.debug("Stop data streaming ...")
		try:
			if self.streaming:
				self.streaming = False
				self.td.join()
				self.tg.join()
				if self.video_scene:
					self.tv.join()
			logging.debug("Data streaming successful stopped!")
		except:
			logging.error("An error occurs trying to stop data streaming")

	def wait_for_recording_status(self, recording_id, status_array = ['init', 'starting',
	'recording', 'pausing', 'paused', 'stopping', 'stopped', 'done', 'stale', 'failed'], timeout = None):
		return self.wait_for_status('/api/recordings/' + recording_id + '/status', 'rec_state', status_array, timeout)

	def wait_for_status(self, api_action, key, values, timeout = None):
		url = self.base_url + api_action
		running = True
		while running:
			req = Request(url)
			req.add_header('Content-Type', 'application/json')
			try:
				response = urlopen(req, None, timeout = timeout)
			except URLError as e:
				logging.error(e.reason)
				return -1
			data = response.read()
			json_data = json.loads(data.decode('utf-8'))
			if json_data[key] in values:
				running = False
			time.sleep(1)
		return json_data[key]

	def wait_until_calibration_is_done(self, calibration_id, timeout = None):
		while True:
			status = self.wait_for_status('/api/calibrations/' + calibration_id + '/status', 'ca_state', ['calibrating', 'calibrated', 'stale', 'uncalibrated', 'failed'], timeout)
			logging.debug("Calibration status %s" % status)
			if status == 'uncalibrated' or status == 'stale' or status == 'failed':
				logging.debug("Calibration %s failed " % calibration_id)
				return False
			elif status == 'calibrated':
				logging.debug("Calibration %s successful " % calibration_id)
				return True

	def wait_until_status_is_ok(self, timeout = None):
		status = self.wait_for_status('/api/system/status', 'sys_status', ['ok'], timeout)
		if status == 'ok':
			return True
		else:
			return False
