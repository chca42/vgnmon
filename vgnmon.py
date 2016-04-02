#!/usr/bin/python3.4
# -*- coding: utf-8 -*-

#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

from http.client import HTTPConnection
from io import StringIO
from bs4 import BeautifulSoup
from datetime import datetime
from argparse import ArgumentParser
from termcolor import colored as col
from pickle import Pickler,Unpickler,HIGHEST_PROTOCOL
from os.path import isfile

import sys
import re

rStop = re.compile(r"name_dm=([0-9]+)&amp;type_dm=stopID\">([^<]+)<")

def getStations(conn, line, staMap):
	staDir0 = []
	staDir1 = []

	conn.request("GET", "/komfortauskunft/ttb/?sessionID=0&exactMatch=1&lineName="+line)
	r = conn.getresponse()
	if r.status != 200:
		print("error:", r.status, r.reason)
	else:
		data = r.read().decode()
		sio = StringIO(data)
		dataE = sio.readlines()
	
		mode = -1
		for l in dataE:
			if l.find("Hinfahrt") >= 0:
				mode = 0
			elif l.find("Rückfahrt") >= 0:
				mode = 1
			
			i0 = l.find("stopID")
			if i0 >= 0:
				i1 = l.find(">",i0)+1
				i2 = l.find("<",i1)
				sta = l[i1:i2]
				m = rStop.search(l)
				#print(m)
				if m:
					staId = int(m.group(1))
					staName = m.group(2)
					staMap[staId] = staName

					if mode == 0:
						staDir0.append(staId)
					else:
						staDir1.append(staId)
				else:
					print("error:", l)
					
	return staDir0,staDir1

def cleanList(l):
	while "\n" in l:
		l.remove("\n")
	for i in range(0,len(l)):
		l[i] = str(l[i])

class Line:
	def __init__(self,name,dir1=None,dir2=None):
		self.name = name
		self.dir1 = dir1
		self.dir2 = dir2
	def hasData(self):
		return (self.dir1 != None) and (self.dir2 != None)
	def desc(self,staMap):
		s = "Direction 1: " + " -> ".join([staMap[d] for d in self.dir1]) + "\n\n"
		s += "Direction 2: " + " -> ".join([staMap[d] for d in self.dir2])
		return s
	def __str__(self):
		return self.name

class LineDB:
	def __init__(self):
		self.db = []
	def get(self,name):
		for d in self.db:
			if d.name == name:
				return d
		l = Line(name)
		self.db.append(l)
		return l
	def __str__(self):
		s = ""
		for d in self.db:
			s += str(d) + "\n"
		return s

class Depart:
	def __init__(self,station,time,line,to):
		self.station = station
		self.time = time
		self.line = line
		self.to = to
		self.delays = []
	def updateDelay(self,time,delay):
		if (len(self.delays) > 0) and (self.delays[-1][1] == delay):
			return
		self.delays.append((time,delay))
		print(col("updated: " + str(self),"yellow"))
	def __str__(self):
		d = ""
		if len(self.delays) > 0:
			d = self.delays[-1][1]
		return "Depart[%d]: %s, %s, %s, to: %s"%(self.station,str(self.time),str(self.line),d,self.to)

class DepartDB:
	def __init__(self):
		self.db = []
	def get(self,station,time,line,to):
		for d in self.db:
			if (d.station == station) and (d.time == time) and (d.line == line) and (d.to == to):
				return d
		d = Depart(station,time,line,to)
		print(col("adding " + str(d),"green"))
		self.db.append(d)
		return d
	def __str__(self):
		s = ""
		for d in self.db:
			s += str(d) + "\n"
		return s

def getDelays(conn,staId,ldb,ddb,staMap):
	conn.request("GET", "http://www.vgn.de/echtzeit-abfahrten/?type_dm=any&nameInfo_dm=%d&stateless_dm=1&dmLineSelectionAll=1&mode=direct&limit=20&sessionID=0" % staId)
	r = conn.getresponse()
	if r.status != 200:
		print("error:", r.status, r.reason)
	else:
		data = r.read().decode()
		soup = BeautifulSoup(data,"html.parser")
		table = soup.find("table",{"class":"EFA"})
		rows = table.findChildren("tr")
		for row in rows:
			cells = row.findChildren("td")
			r = []
			for cell in cells:
				l = list(cell.strings)
				cleanList(l)
				r.append(l)
			
			if len(r) >= 4:
				date = datetime.strptime(r[0][0],"%d.%m. %H:%M")
				date = date.replace(year=datetime.now().year)
				line = r[2][0]
				to = ' '.join(r[3][0].split())

				l = ldb.get(line)
				d = ddb.get(staId,date,l,to)
				
				if len(r[0]) > 1:
					delay = r[0][1]
					d.updateDelay(datetime.now(),delay)

if __name__ == "__main__":
	
	ap = ArgumentParser(description="Monitor VGN Timeliness")
	ap.add_argument("-l", dest="line", help="query lines")
	ap.add_argument("-L", dest="lineall", help="query all line departures")
	ap.add_argument("-d", nargs="+", dest="depart", help="query departure")
	ap.add_argument("-s", dest="show", action="store_true", help="show database")
	args = ap.parse_args()
	print(args)

	if isfile("data.pickle"):
		p = Unpickler(open("data.pickle","rb"))
		ddb = p.load()
		ldb = p.load()
		staMap = p.load()
	else:
		ddb = DepartDB()
		ldb = LineDB()
		staMap = {}
		
	writeUpdate = False
	
	if args.line or args.lineall:
		lname = ""
		if args.line:
			lname = args.line
		else:
			lname = args.lineall

		l = ldb.get(lname)
			
		if not l.hasData():
			print("line not in database, fetching ...")
			c = HTTPConnection("www.vgn.de")
			staDir0,staDir1 = getStations(c,lname,staMap)
			l.dir1 = staDir0
			l.dir2 = staDir1
			writeUpdate = True
		print(l.desc(staMap))
		
	if args.lineall:
		c = HTTPConnection("www.vgn.de")
		l = ldb.get(args.lineall)
		ids = {}
		for e in l.dir1:
			ids[e] = staMap[e]
		for e in l.dir2:
			ids[e] = staMap[e]

		for i in ids.keys():
			print("fetching", ids[i])
			getDelays(c,i,ldb,ddb,staMap)
		writeUpdate = True
		
	if args.depart:
		c = HTTPConnection("www.vgn.de")
		for d in args.depart:
			print("fetching", d)
			staId = -1
			for i in staMap.items():
				if i[1] == d:
					staId = i[0]
			if staId >= 0:
				getDelays(c,staId,ldb,ddb,staMap)
				#print(ddb)
				writeUpdate = True
			else:
				print("error: station not found:", d)
		
		
	if args.show:
		print(ddb)
	
	if writeUpdate:
		f = open("data.pickle","wb")
		p = Pickler(f, HIGHEST_PROTOCOL)
		p.dump(ddb)
		p.dump(ldb)
		p.dump(staMap)
		f.flush()
		f.close()

