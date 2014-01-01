# the engine class collects user input (local/client mode) and moves 
# the simulation forward in time, generating snapshots (local/server mode)
# also the snapshots are being rendered (local/client mode)

import sys
import direct.directbase.DirectStart
from direct.showbase.DirectObject import DirectObject
from direct.gui.DirectGui import *
from panda3d.core import *
from direct.task import Task
from copy import *
import logging
import time
import math

# Engine Modes
LOCAL = 1
CLIENT= 2
SERVER= 4
#PLAYING_SERVER = 8

# Entity fields
ID   = 0
POS  = 1
VEL  = 2

# Key Actions
NKEYS= 5
UP   = 0
DOWN = 1
LEFT = 2
RIGHT= 3
RESET= 4

# Message Types
CONNECT  = 200
INIT     = 201
KEYS     = 202
SNAPSHOT = 210


# Constants
DISTANCE = 55
MAXX     = 20
MAXY     = 15
MAXV	 = 25
ACC		 = 2.5
GRAV     = 6.0

class Entity():
    def __init__(self, id=0, pos=Point3(0,DISTANCE,0), vel=Point3(0,0,0), **kwargs):
        self.id = id
        self.pos = pos
        self.vel = vel
        self.keys = {}
        self.lastchange = 0
        for i in range(NKEYS):
            self.keys[i] = 0
    

class Snapshot():
    def __init__(self, time=0):
        self.time = time
#        self.entities = []
        self.index = {}

    def pack(self, time = 0):
        info = []
        for id in self.index:
            ent = self.index[id]
            if time and ent.lastchange and ent.lastchange < time:
                continue
            info.append((id, tuple(ent.pos), tuple(ent.vel)))
        return [self.time, info]

    def unpack(self, data):
        self.time = data[0]
        for id, pos, vel in data[1]:
            try:
                ent = self.index[id]
                ent.pos = Point3(pos)
                ent.vel = Point3(vel)
            except KeyError:
                self.addEntity(Entity(id=id, pos=Point3(pos), vel=Point3(vel))) 

    def addEntity(self, entity):
#        self.entities.append(entity)
        if entity.id in self.index:
            raise Exception('ID error')
        self.index[entity.id] = entity
#        print ("Added Entity %d", entity.id)

class Player():
    def __init__(self, id=id):
        self.id = id
        self.lastRecvSnap = 0

        

class Engine(DirectObject):
    def __init__(self, mode, time=0, net=None, tickrate = 60, snaprate=20):
        self.log = logging.getLogger('Engine')
        self.time = 0
        self.timeUpdate = 0
#        self.timediff = 0
        self.lasttick = 0
        self.lastsnap = 0
        self.lastreset = 0
        self.dt = 1. / tickrate
        self.dtNextSnap = 1. / snaprate
        self.nBuff = 1
        self.snapshots = []
        self.cursnap = Snapshot()
        self.nextsnap= Snapshot()
        self.mode = mode
        self.models = {}
        self.players = {}
        if mode == CLIENT:
            self.lastRecvSnap = 0
        if not mode == LOCAL:
            if net is None:
                raise Exception('no network connection provided in non-local mode')
            self.net = net
            self.initnetwork()    
        if not mode == SERVER:
            self.initcontrols()
            self.initmodels()
        else:
            self.initentities()
            self.oldsnapshots = []
        
        taskMgr.add(self.mainLoop, "EngineMain", 1000)
  
    def initentities(self):
        self.playerID = -1
        self.playerobj = Entity(id = self.playerID, vel=Point3(0.,0.,0.) )
        self.cursnap.addEntity(self.playerobj)

    def initmodels(self):
        self.playerID = -1
        self.addPlayer(self.playerID)
        self.playerobj = Entity(id = self.playerID, vel=Point3(0.,0.,0.) )
        self.models[self.playerID] = self.loadObject("dot")
        self.cursnap.addEntity(self.playerobj)

    def initcontrols(self):
        self.keys = {}
        for i in range(NKEYS):
            self.keys[i] = 0
        self.accept("arrow_left",     self.setKey, [LEFT, 1])
        self.accept("arrow_left-up",  self.setKey, [LEFT, 0])
        self.accept("arrow_right",    self.setKey, [RIGHT, 1])
        self.accept("arrow_right-up", self.setKey, [RIGHT, 0])
        self.accept("arrow_up",       self.setKey, [UP, 1])
        self.accept("arrow_up-up",    self.setKey, [UP, 0])
        self.accept("arrow_down",     self.setKey, [DOWN, 1])
        self.accept("arrow_down-up",  self.setKey, [DOWN, 0])
        self.accept("space",          self.setKey, [RESET, 1])
        self.accept("space-up",       self.setKey, [RESET, 0])


    def setKey(self, key, val): 
        self.keys[key] = val

    def initnetwork(self):
        if self.mode == CLIENT:
            self.net.handlers[SNAPSHOT] = self.recvSnapshot
            self.net.handlers[INIT] = self.initClient
#            time.sleep(2.)
            while not self.net.connected:
                time.sleep(0.3)
            self.net.sendToServer(True, msgtype=CONNECT, reliable=True, out_of_line=True)
        if self.mode & SERVER:
            self.net.handlers[CONNECT] = self.welcomeClient
            self.net.handlers[KEYS] = self.recvKeys

    def welcomeClient(self, data, id=None):
        self.log.debug("Client connected")
        self.addPlayer(id)
        self.net.sendDataToID([self.time, self.dtNextSnap, id], id, reliable=True, out_of_line=True, msgtype=INIT)
        
    def addPlayer(self, id):
        self.players[id] = Player(id)

    def initClient(self, data):
        servertime = data[0] - (data[1] * self.nBuff)
        self.log.debug("received Reply from server, server time: %f" % servertime)
        self.timeUpdate = servertime
        self.time = servertime
        for snap in self.snapshots[:]:
            if snap.time < self.time:
                self.snapshots.remove(snap)

    def mainLoop(self, task):
#        self.time = task.time
        if self.timeUpdate:
            globalClock.setRealTime(self.timeUpdate)
            self.timeUpdate = 0
            self.time = self.timeUpdate
        else:
            self.time = globalClock.getRealTime()        
        dt = self.time - self.lasttick
        if dt > self.dt:
            self.lasttick = self.time
            if not self.mode == CLIENT:
                if self.time - self.lastsnap > self.dtNextSnap:
                    self.lastsnap = self.time
                    self.step(1)
                else:
                    self.step(0)
            if not self.mode == SERVER:
                self.gatherInput()                                
            if (self.time > self.nextsnap.time) and len(self.snapshots):
                self.cursnap = (self.nextsnap)
                # l = len(self.snapshots)
                self.nextsnap = self.snapshots.pop()
		if not self.mode == SERVER:
			self.render()
        return Task.cont

    def step(self, mode):
#        print "step", self.dt, self.time - self.lasttick, mode
        dt = self.time - self.cursnap.time
        nextsnap = Snapshot(self.time)
        for id in self.cursnap.index:
            ent = (self.cursnap.index[id])
#            print ent.pos
            ent.pos += ent.vel * dt
#            ent.vel[2] = 5 * math.sin(ent.pos[0])
            if abs(ent.pos[0]) > MAXX: 
                ent.vel[0] *= -1.
            if abs(ent.pos[2]) > MAXY: 
                ent.vel[2] *= -1.
            acc = ACC
            maxv= MAXV
            grav= GRAV
            ent.vel[2] -= grav * dt
            if ent.keys[UP]:
                ent.vel[2] += acc * dt
            elif ent.keys[DOWN]:
                ent.vel[2] -= acc * dt
            if ent.keys[LEFT]:
                ent.vel[0] -= acc * dt
            elif ent.keys[RIGHT]:
                ent.vel[0] += acc * dt
            if ent.keys[RESET]:
                ent.pos = Point3(0,DISTANCE,0)
                ent.vel = Point3(0,0,0)

            if ent.vel[2] > maxv: ent.vel[2] = maxv
            elif ent.vel[2] < -maxv: ent.vel[2] = -maxv
            if ent.vel[0] > maxv: ent.vel[0] = maxv
            elif ent.vel[0] < -maxv: ent.vel[0] = -maxv
            nextsnap.addEntity(ent)

        self.addSnapshot(nextsnap)
        if self.mode & SERVER:
#            self.cursnap.time = self.time
#            print data
            if mode == 1:
                data = nextsnap.pack()
                self.net.broadcast(data, msgtype=SNAPSHOT, reliable=False)
#            self.net.broadcast(["server",repr(data)], msgtype=201)

    def test(self, data):
        self.log.debug("dum")

    def render(self):        
        dt = self.time - self.cursnap.time
        frac = dt / (self.nextsnap.time - self.cursnap.time)
        #print "time:", self.time, self.cursnap.time, dt, frac
        if frac < 0:
            return
        for id in self.models:
            try:
                curEnt = self.cursnap.index[id]
                nextEnt= self.nextsnap.index[id]
                self.models[id].setPos(curEnt.pos + (nextEnt.pos - curEnt.pos) * frac)
                #print frac
            except KeyError:
                self.log.warning("entity missing %d" %id)

    def gatherInput(self):
        if self.mode & LOCAL:
            self.recvKeys([self.time, 0, self.keys], id=self.playerID)
        if self.mode == CLIENT:
            self.net.sendToServer([self.time, self.lastRecvSnap, self.keys], msgtype=KEYS, reliable=False)

    def recvKeys(self, data, id=id):
        eid = -1
        time = data[0]
        lastsnap = data[1]
        keys = data[2]
        self.players[id].lastRecvSnap = lastsnap
        self.cursnap.index[eid].keys.update(keys)

    def recvSnapshot(self, data):
#        self.log.debug("received snapshot, time %f", data[0])
        if data[0] > self.lastRecvSnap:
            self.lastRecvSnap = data[0]
        if data[0] < self.nextsnap.time:
            return
        snapshot = Snapshot()
        snapshot.unpack(data)
        self.addSnapshot(snapshot)

    def addSnapshot(self, snapshot):
        if snapshot.time < self.nextsnap.time:
            return
        elif self.nextsnap.time == 0:
#        elif len(self.snapshots) == 0:
            self.nextsnap = snapshot
#            print 'go'
        else:
            i = 0
            while i < len(self.snapshots):
                if snapshot.time > self.snapshots[i].time:
                    break
                i += 1
            self.snapshots.insert(i, snapshot)
        

    def loadObject(self, tex = None, pos = Point3(0,DISTANCE,0), scale = 1,
                   transparency = True):
        obj = loader.loadModel("models/plane") #Every object uses the plane model
        obj.reparentTo(camera)              #Everything is parented to the camera so
                                      #that it faces the screen
        obj.setPos(pos) #Set initial position
        obj.setScale(scale)                 #Set initial scale
        obj.setBin("unsorted", 0)           #This tells Panda not to worry about the
                                      #order this is drawn in. (it prevents an
                                      #effect known as z-fighting)
        obj.setDepthTest(False)             #Tells panda not to check if something
                                      #has already drawn in front of it
                                      #(Everything in this game is at the same
                                      #depth anyway)
        if transparency: obj.setTransparency(1) #All of our objects are trasnparent
        if tex:
            tex = loader.loadTexture("textures/"+tex+".png") #Load the texture
            obj.setTexture(tex, 1)                           #Set the texture
            
        return obj
