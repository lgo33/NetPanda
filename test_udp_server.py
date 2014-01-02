#!/usr/bin/env python

from pandac.PandaModules import loadPrcFileData
loadPrcFileData("", "window-type none")

import direct.directbase.DirectStart

from direct.showbase.DirectObject import DirectObject
from pandac.PandaModules import *
from direct.task import Task
from direct.distributed.PyDatagram import PyDatagram
from direct.distributed.PyDatagramIterator import PyDatagramIterator
from UDPconnection_thread import *
from nbc import *
import logging
from time import ctime
from engine import *


class handlers():
    @staticmethod
    def printmessage(msg):
        print msg

    @staticmethod
    def testing(msg, id=id):
        pos = msg['pos']
        # print pos[0], pos[1], pos[2]
        # print len(msg['extralong'])
        print msg['num'], msg['time'], len(msg['extralong']), id

class World(DirectObject):
    def __init__(self, nbc=None, server=None):
        self.logger = logging.getLogger('World')
        self.logger.debug('World started at %s', ctime())
        # Start our server up
        if server is None:
            self.server = UDPserver(9099)
        else:
            self.server = server
        self.cnt = 0
        # Create a task to print and send data
        # taskMgr.doMethodLater(1., self.commtest, "Communication Test")
        self.server.handlers[100] = handlers.printmessage
        self.server.handlers[101] = handlers.testing
        self.buffer = {}
        self.engine = Engine(SERVER, net=self.server)
        if nbc is not None:
            self.nbc = nbc
            taskMgr.add(self.pollkeys, "pollKeys", -50)            


    def pollkeys(self, task):
        key = self.nbc.get_data()
        if key:
            if key  == '\x1b':
                self.logger.debug("Exit by User")
                self.quit()
            elif key == 't':
                print self.engine.players[1].lastRecvSnap
            elif key == 'p':
                for client in self.server.commBuffer:
                    print client.id, client.ping
            elif key == 'b':
                self.server.broadcast(ctime(), msgtype=SMSG)
            elif key == 'd':
                print 'disconnecting:'
                for client in self.server.commBuffer:
                    self.server.disconnect("", id=client.id)
            elif key == '?':
                print 'help'
        return Task.cont
   
    def quit(self):
        self.server.shutdown()
        taskMgr.running = False
#        base.closeWindow(base.win)
#        sys.exit()

if __name__ == '__main__':
    logging.basicConfig(format='%(relativeCreated)-8d%(name)-12s%(levelname)-8s|%(funcName)-16s\t%(message)s', datefmt='%m/%d/%Y %H:%M:%S ', level=logging.DEBUG)
    with NonBlockingConsole() as nbc:
        s = UDPserver(9099)
        w = World(nbc=nbc, server=s)
        run()
