# streaming.py : A demo for data streaming
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

import time
import json
from tobiiglassesctrl import TobiiGlassesController


def main():

	tobiiglasses = TobiiGlassesController("192.168.71.50")
	print(tobiiglasses.get_battery_status())


	#Get the bounds of the viewable range
	print("Enter x upperbound:")
	x_upper = int(input())

	print("Enter x lowerbound:")
	x_lower = int(input())


	print("Enter y upperbound:")
	y_upper = int(input())

	print("Enter y lowerbound:")
	y_lower = int(input())
	
	print("Enter time to run in seconds:")
	tt = int(input())

	tobiiglasses.start_streaming()
	print("Please wait ...")
	time.sleep(3.0)

	for i in range(tt):
		time.sleep(1.0)
# 		print("Head unit: %s" % tobiiglasses.get_data()['mems'])
# 		print("Left Eye: %s " % tobiiglasses.get_data()['left_eye'])
# 		print("Right Eye: %s " % tobiiglasses.get_data()['right_eye'])
# 		print("Gaze Position: %s " % tobiiglasses.get_data()['gp'])

		x_pos = tobiiglasses.get_data()['gp']['gp'][0]
		y_pos = tobiiglasses.get_data()['gp']['gp'][1]
		
		print("Test number " + i)
		print("X Position: " + x_pos)
		print("Y Position: " + y_pos)
		

		#if out of bounds in the x axis
		if (x_pos > x_upper or x_pos < x_lower):
			print('X out of bounds')
			print('\a') #makes a beeping noise
		elif (y_pos > y_upper or y_pos < y_lower):
			print('Y out of bounds')
			print('\a') #makes a beeping noise
		else:
			print('In bounds')




		print("Gaze Position 3D: %s " % tobiiglasses.get_data()['gp3'])

	tobiiglasses.stop_streaming()
	tobiiglasses.close()



if __name__ == '__main__':
    main()
