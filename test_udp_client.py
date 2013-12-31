from pandac.PandaModules import ConfigVariableString 
ConfigVariableString("window-type", "none").setValue("none")

import direct.directbase.DirectStart

from direct.showbase.DirectObject import DirectObject
from pandac.PandaModules import * 
from direct.task import Task 
from direct.distributed.PyDatagram import PyDatagram 
from direct.distributed.PyDatagramIterator import PyDatagramIterator 
from UDPconnection import *


class handlers():
    @staticmethod
    def printmessage(msg):
        print msg


class World(DirectObject):
    def __init__(self):
        # Connect to our server
        userdata = {}
        userdata['name'] = "Elke"
        userdata['pw'] = 'secret'
        self.client = UDPclient(userdata, 9199, '160.39.139.138', 9099)
        # self.client = UDPclient(userdata, 9199, '127.0.0.1', 9099)
        # Create a task to print and send data
        # taskMgr.doMethodLater(2.0, self.printTask, "printData")
        self.n = 0
        self.frameTime = ClockObject()
        self.client.handlers[10] = handlers.printmessage
        taskMgr.doMethodLater(1, self.testcom, "test")
        taskMgr.doMethodLater(3, self.testcom2, "test2")
        self.client.handlers[78] = self.getfile
        self.client.handlers[79] = self.writefile
        self.buffer = {}

    def getfile(self, data):
        filename = data['filename']
        if filename not in self.buffer:
            self.buffer[filename] = {}
            self.buffer[filename]['data'] = []
        self.buffer[filename]['data'].append(data['data'])
        self.client.sendToServer("dum.dat", msgtype=77, reliable=1)

    def writefile(self, filename):
        f = open('dum2.dat', 'w')
        for chunk in self.buffer[filename]['data']:
            f.write(chunk)
        f.close()
        del self.buffer[filename]
        print "file written"

    def testcom(self, task):
        data = {"n": self.n}
        self.n += 1
        if self.client.commBuffer:
            cb = self.client.commBuffer[0]
            data["ping"] = [cb.ping, min(cb.lastpings), max(cb.lastpings)]
        # self.client.sendData(data, self.client.serverAddr, msgtype=10, out_of_line=False, seqNum=3)
        self.client.sendToServer(data, msgtype=10, out_of_line=True, reliable=1)
        return Task.again

    def testcom2(self, task):
        if self.client.connected:
            self.client.sendToServer('dum.dat', msgtype=77, reliable=1)


w = World()
run()
