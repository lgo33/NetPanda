from pandac.PandaModules import loadPrcFileData
loadPrcFileData('','show-frame-rate-meter 1')
import sys
import direct.directbase.DirectStart
from direct.showbase.DirectObject import DirectObject
from direct.gui.DirectGui import *
from panda3d.core import *
from messages import *
from engine import *
from UDPconnection_thread import *
from time import ctime


MAX_ATTEMPTS = 50

# info = infopanel('infotext')
class World(DirectObject):
    """World Class contains the main objects and handles network communication"""
    def __init__(self):
        self.log = logging.getLogger('World')
        self.log.debug("World started at %s", ctime())
        self.mesmgr = messageManager(msghandler=self.sendmsg)
        self.accept("enter", self.mesmgr.showtextfield)
        self.accept("escape", self.quit)
        self.info = infopanel("infotext")
        self.info.setinfo('debug information here')
#        taskMgr.add(self.info.showtime, "ShowTime")
        taskMgr.add(self.showinfo, "ShowInfo")
        self.netclient = None
        self.netinit('127.0.0.1', 9099)
#        self.netinit('adhara.usm.uni-muenchen.de', 8888)
#        self.engine = Engine(LOCAL)


    def showinfo(self, task):
        info = str(self.engine.cursnap.index[self.engine.playerID].keys[4]) + " | " + str(len(self.engine.snapshots)) + " " + "%03.1f" % self.engine.time
        vel = self.engine.cursnap.index[self.engine.playerID].vel
        info = "%04.1f %04.1f %04.1f" % (vel[0], vel[1], vel[2])
        if self.netclient is not None:
            info += "%7.3f" % self.netclient.getPing()
        self.info.setinfo(info)
        return Task.again

    def sendmsg(self, txt):
        if self.netclient.connected:
            self.netclient.sendToServer(txt, msgtype=CMSG_CHAT, reliable=True, out_of_line=True)
        else:
            self.outtext('not connected', sender='')

    def outtext(self, txt, **kwargs):
        self.mesmgr.addText(txt, **kwargs)

    def netinit(self, ip, port):
        userdata = {}
        userdata['name'] = "Elke2"
        userdata['pw'] = 'secret2'
        self.netclient = UDPclient(userdata, port ,ip, commTicks=20)
        self.netclient.handlers[SMSG_CHAT] = self.showchatmsg
        self.netclient.handlers[SMSG] = self.showservermsg
        self.engine = Engine(CLIENT, net=self.netclient)
#        self.engine = Engine(LOCAL+SERVER, net=self.netclient)

    def showchatmsg(self, data):
        self.mesmgr.addText(data[1], sender=data[0])

    def showservermsg(self, data):
        self.mesmgr.addText(data, sender='server')
            
    def quit(self):
#        self.netclient.disconnect()
        self.log.debug('Exit by User')
        if self.netclient is not None:
            self.netclient.running = False
        taskMgr.running = False
        


class infopanel:
    """
    Output debug information
    """

    def __init__(self, initialtext=''):
        self.info = TextNode('info')
        self.info.setText(initialtext)
        self.info.setCardColor(0, 0, 0, 0.2)
        self.info.setCardAsMargin(0.3, 0.3, 0.3, 0.3)
        self.info.setTextColor(1, 0.5, 0.5, 1)
        self.info.setShadow(0.05, 0.05)
        self.info.setShadowColor(0, 0, 0, 1)
        self.info.setAlign(TextNode.ARight)
        self.infoNodePath = base.a2dTopRight.attachNewNode(self.info)
        self.infoNodePath.setScale(0.07)
        self.infoNodePath.setPos(-0.02, 0.0, -0.1)

    def setinfo(self, text):
        self.info.setText(text)

    def showtime(self, task):
        self.info.setText("%03.1f" % task.time)
        return Task.cont


if __name__ == '__main__':
    logging.basicConfig(format='%(relativeCreated)-8d%(name)-12s%(levelname)-8s|%(funcName)-16s\t%(message)s', datefmt='%m/%d/%Y %H:%M:%S ', level=logging.DEBUG)
#    logging.basicConfig(format='%(msecs)d|%(name)s|%(levelname)s|%(funcName)s\t%(message)s', datefmt='%m/%d/%Y %H:%M:%S ', level=logging.ERROR)
   # run main loop
    w = World()
    run()
