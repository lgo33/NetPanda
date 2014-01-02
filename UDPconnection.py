from pandac.PandaModules import QueuedConnectionManager, QueuedConnectionListener
from pandac.PandaModules import QueuedConnectionReader, ConnectionWriter
from direct.distributed.PyDatagram import PyDatagram
from direct.distributed.PyDatagramIterator import PyDatagramIterator
from pandac.PandaModules import NetDatagram
from direct.task.Task import Task
from pandac.PandaModules import *
#from panda3d.core import Thread
import threading
import numpy as np
import rencode
import bisect
import collections
import copy
import math
import sys
import hashlib
import logging
# import cPickle
# import logger

# Constant Values
MAX_ATTEMPTS = 10

# Message Types:
MSG_NONE            = 0
CMSG_AUTH           = 1
SMSG_AUTH_RESPONSE  = 2
CMSG_CHAT           = 3
SMSG_CHAT           = 4
SMSG                = 5
CMSG_DISCONNECT_REQ = 6
SMSG_DISCONNECT_ACK = 7
CONFIRM             = 8
KEEP_ALIVE          = 9
MULT                = 10
DESYNC              = 11

#Message Fields:
SEQN        = 0         # Sequence number
AKN         = 1         # Aknowledge reception of messages up to this number
MSG_TYPE    = 2         # Message type
OOL         = 3         # Message can be executed out of line
OAKN        = 4         # Aknowledge reception of messages that are out order
DATA        = 5         # Message data
ADDR        = 6         #
TIME        = 7         #
ENCODED     = 8         # Message is already encoded for transmission

class commBuffer():
    """
    buffers messages for possible resending or incompleteness, timeouts not implemented yet
    """
    def __init__(self, id=None, addr=None, maxbuf=100, lastRecv=0, ping=0.1):
        self.id = id
        self.rid = 0
        self.addr = NetAddress()
        self.addr.setHost(addr.getIpString(), addr.getPort())
        self.sendBuffer = []
        self.recvBuffer = []
        self.incompleteRecvBuffer = []
        self.seqNumber  = 1
        self.rseqNumber = 0
        self.lastAKN = 0
        self.lastConfirmed = 0
        # self.
        self.lastRecv = lastRecv
        self.lastSend = 0
        self.ping = ping
        self.lastpings = []
        self.lastpingsSqr = []
        self.maxbuf = maxbuf

    def addSendMessage(self, msg, msgtype=0, sendtime=0):
        # add a message to the send-buffer, it will be resend until a confirmation is received
        msg[SEQN] = self.seqNumber
        msg[TIME] = sendtime
        self.sendBuffer.append(msg)
        self.seqNumber += 1
        return msg[SEQN]

    def addRecvMessage(self, msg, recvtime=0):
        # add an out of order received message to the receive-buffer
        if len(self.recvBuffer) >= self.maxbuf:
            return
        seqNum = msg[SEQN]
        recvsqn = [m[SEQN] for m in self.recvBuffer]
        if seqNum in recvsqn:
            return
        msg[TIME] = recvtime
        ind = bisect.bisect(recvsqn, seqNum)
        self.recvBuffer.insert(ind, msg)

    def confirm(self, seqNum, time=None):
        # look for confirmed messages in the send-buffer
        msg = 0
        while self.sendBuffer and self.sendBuffer[0][SEQN] <= seqNum:
            msg = self.sendBuffer.pop(0)
            self.lastConfirmed = seqNum
        if time is not None and msg and msg[TIME]:
            ping = time - msg[TIME]
            self.addping(ping)

    def addping(self, ping):
        self.lastpings.append(ping)
        self.lastpingsSqr.append(ping ** 2)
        if len(self.lastpings) > 10:
            self.lastpings.pop(0)
            self.lastpingsSqr.pop(0)
            sigma = np.std(self.lastpings)            
            self.ping = np.mean(self.lastpings) + np.std(self.lastpings)
        else:
            self.ping = ping * 1.1

    def getRecvBuffer(self):
        # print "looking for messages in getRecvBuffer ", self.rseqNumber, len(self.recvBuffer)
        # get (and remove) previously received messages that are now in order from the receive-buffer
        while self.recvBuffer and self.recvBuffer[0][SEQN] == self.rseqNumber + 1:
            self.rseqNumber += 1
            yield self.recvBuffer.pop(0)

    def remove(self, seqNum):
        # remove messages from the send-buffer
        if not isinstance(seqNum, collections.Iterable):
            seqNum = [seqNum]
        for sn in seqNum:
            for msg in self.sendBuffer[:]:
                if msg[SEQN] == sn:
                    self.sendBuffer.remove(msg)
                    break

    def getPartialMsgIndex(self, identifier):
        for msg in self.incompleteRecvBuffer:
            if msg['id'] == identifier:
                return self.incompleteRecvBuffer.index(msg)
        return -1

    def crPartialMsg(self, identifier, nchunks):
        msg = {'id': identifier, 'total': nchunks, 'done': [False]*nchunks, 'data': [""] * nchunks, 'lastupdate': 0}
        self.incompleteRecvBuffer.append(msg)
        return self.incompleteRecvBuffer.index(msg)

    def addPartialMsg(self, msg, time=None):
        # add partial message to the buffer, return complete message and remove from buffer when all parts are received
        msgtype, identifier, nchunks, ichunk  = msg[OAKN]
        nchunks = int(nchunks)
        ichunk = int(ichunk)
        ind = self.getPartialMsgIndex(identifier)
        if ind < 0:
            ind = self.crPartialMsg(identifier, nchunks)
        pmsg = self.incompleteRecvBuffer[ind]
        pmsg['data'][ichunk] = msg[DATA]
        pmsg['done'][ichunk] = True
        if time and msg[SEQN] < 0:
            pmsg['lastupdate'] = time
        # print pmsg['done']                
        if sum(pmsg['done']) == nchunks:            
            # msg[DATA] = rencode.loads("".join(pmsg['data']))            
            msg[DATA] = rencode.loads("".join(pmsg['data']))
            msg[MSG_TYPE] = msgtype
            self.incompleteRecvBuffer.remove(pmsg)
        return msg


class UDPconnection():
    """
    base class for UDP server and client, handles basic communication (decoding/encoding), buffering and resending
    """
    def __init__(self, port='9099', timeout=3.0, commTicks=50, resendTime=0.33, reliable=0, concurrent=10, maxlength=480):
        self.logger = logging.getLogger('UDPcon')
        self.port = port
        # Start the UDP Connection
        self.cManager = QueuedConnectionManager()
        self.cReader = QueuedConnectionReader(self.cManager, 0)
        self.cWriter = ConnectionWriter(self.cManager, 0)
        self.conn = self.cManager.openUDPConnection(self.port)
        self.cReader.addConnection(self.conn)
        self.handlers = {}
        self.nextID = 1
        self.commBuffer = []
        self.conAddresses = []
        self.conIDs = []
        self.timeout = timeout
        self.commTicks = commTicks
        self.commTime = 1.0 / self.commTicks
        self.time = ClockObject()
        self.resendTime = resendTime
        self.reliable = reliable
        self.concurrent = concurrent
        self.maxlength = maxlength
        self.multMsgID = 0
        # receive data
        taskMgr.add(self.listendata, "Incoming Data Listener", -40)
        # send the data in the send buffer
        taskMgr.doMethodLater(self.commTime, self.batch, "Batch")
        self.handlers[KEEP_ALIVE] = self.reply
        self.handlers[CONFIRM] = self.sync
#        logging.debug('UDPconnection created')
        self.logger.debug('UDPconnection created')

    def batch(self, task):
        # recurring tasks
        self.timenow = self.time.getFrameTime()
        self.sendDataBuffer()
        self.chkCommBuffers()
        return Task.again

    def listendata(self, task):
        # function that listens for incoming data, updating communication clock and calling handler-functions, should be added to taskMgr
        self.time.tick()
        data = self.getData()
        if data:
            self.timenow = self.time.getFrameTime()
            # we only accept authentication requests from not-connected remote machines, all other incomming data is discarded
            for d in data:
#                print "incoming: ", d[MSG_TYPE], d[SEQN]
                if d[MSG_TYPE] == CMSG_AUTH or d[MSG_TYPE] == SMSG_AUTH_RESPONSE:
#                if d[MSG_TYPE] == CMSG_AUTH:
                    if d[MSG_TYPE] in self.handlers:
                        self.handlers[d[MSG_TYPE]](d[DATA], d[ADDR])
                    continue
                ind = self.getCommBufferByAddr(d[ADDR])
                if ind < 0:
                    continue

                self.commBuffer[ind].lastRecv = self.timenow
                # remove confirmed messages
                self.commBuffer[ind].confirm(d[AKN], time=self.timenow)

                if d[MSG_TYPE] == MULT:
                    if d[SEQN] > 0 and d[SEQN] <= self.commBuffer[ind].rseqNumber:
                        continue    
                    d = self.commBuffer[ind].addPartialMsg(d, time=self.timenow)                    
                else:
                    if d[OAKN]:
                        self.commBuffer[ind].remove(d[OAKN])

                # discard message if already received
                if d[SEQN] > 0 and d[SEQN] <= self.commBuffer[ind].rseqNumber:
                    continue

                execute = []
                # unreliable messages are always executed when they are received without sending a confirmation
                if d[SEQN] < 0:
                    execute = [d]
                else:
                    # if received message is the next in line or can be executed out of line -> execute=1, otherwise store in recvBuffer
                    if d[SEQN] == self.commBuffer[ind].rseqNumber + 1:
                        self.commBuffer[ind].rseqNumber += 1
                        execute = [d]
                    else:
                        if d[OOL]:
                            execute = [d]
                        self.commBuffer[ind].addRecvMessage(d, recvtime=self.timenow)

                # look for messages that are now in line to be processed
                for msg in self.commBuffer[ind].getRecvBuffer():
                    if not msg[OOL]:
                        execute.append(msg)

                # call handler and pass data to it
                for msg in execute:
                    if msg[MSG_TYPE] in self.handlers and not msg[MSG_TYPE] == MULT:
                        try:
                            self.handlers[msg[MSG_TYPE]](msg[DATA], id=self.commBuffer[ind].id)
                        except:
                            self.handlers[msg[MSG_TYPE]](msg[DATA])
        return Task.cont

    def chkCommBuffers(self):
        for cb in self.commBuffer:
            for msg in cb.incompleteRecvBuffer[:]:
                if msg['lastupdate'] and (self.timenow - msg['lastupdate']) > self.timeout:
                    cb.incompleteRecvBuffer.remove(msg)

        # timeout not yet fully implemented
        return

        remove = []
        for cb in self.commBuffer:
            if (self.time.getFrameTime() - cb.lastRecv) > self.timeout:
                remove.append(cb.id)
        for id in remove:
            ind = self.getCommBufferByID(id)
            del self.commBuffer[ind]

    def getCommBufferByAddr(self, addr):
        # self.conAddresses = [(cb.addr.getIp(), cb.addr.getPort()) for cb in self.commBuffer]
        try:
            ind = self.conAddresses.index((addr.getIp(), addr.getPort()))
        except ValueError:
            ind = -1
        return ind

    def getCommBufferByID(self, id):
        # print type(self.commBuffer)
        # self.conIDs = [cb.id for cb in self.commBuffer]
        try:
            ind = self.conIDs.index(id)
        except ValueError:
            ind = -1
        return ind

    def encode(self, data):
        # encode the data with rencode
        # return rencode.dumps(data)
        return rencode.dumps(data)
        

    def decode(self, data):
        # decode the data with rencode
        # return rencode.loads(data)
        return rencode.loads(data)

    def sync(self, data, id=None):
        if id is not None:
            ind = self.getCommBufferByID(id)
            if abs(data[0] - self.commBuffer[ind].lastKeepAlive) < 1e-3:
                ping = self.time.getFrameTime() - data[0]
                self.commBuffer[ind].addping(ping)

    def reply(self, data, id=None):
        if id is not None:
            data = [data, self.time.getFrameTime()]
            self.sendDataToID(data, id, msgtype=CONFIRM, reliable=False)

    def sendDataBuffer(self):
        # all messages that haven't been confirmed in ping + sigma(ping) will be resend
        for buff in self.commBuffer:
            addr = buff.addr
            # timenow = self.time.getFrameTime()
            timenow = self.timenow
            sent = 0
            for msg in buff.sendBuffer:
                oakn = [m[SEQN] for m in buff.recvBuffer]
                if len(oakn) > 5:
                    oakn = oakn[0:4]
                oakn_encoded = self.encode(oakn)
                if self.time.getFrameTime() - msg[TIME] > buff.ping:
                    # self.sendData(msg['data'], addr, msgtype=msg['msgtype'], seqNum=msg['sqn'], encode=False)
                    msg[AKN] = buff.rseqNumber
                    if not msg[MSG_TYPE] == MULT:
                        if msg[ENCODED]:
                            msg[OAKN] = oakn_encoded
                        else:
                            msg[OAKN] = oakn
                    buff.lastAKN = msg[AKN]
                    self.sendMessage(msg, addr)
                    msg[TIME] = self.time.getFrameTime()
                    sent += 1
                    if sent >= self.concurrent:
                        break
            if timenow - buff.lastRecv > self.resendTime or buff.lastAKN < buff.rseqNumber:
                # self.sendDataToID("", buff.id, msgtype=KEEP_ALIVE, out_of_line=True)
                buff.lastKeepAlive = timenow
                self.sendDataToID(timenow, buff.id, msgtype=KEEP_ALIVE, reliable=False)

    def sendMessage(self, msg, addr):
        # print "sending!: ", msg, addr.getIpString(), addr.getPort()
        myPyDatagram = self._crDatagram(msg)
        # print "size: ", sys.getsizeof(myPyDatagram), "type: ", msg[MSG_TYPE], "data: ", msg[DATA]
        self.cWriter.send(myPyDatagram, self.conn, addr)

    def sendDataToID(self, data, cID, reliable=None, **kwargs):
        msg = self._crMessage(data, **kwargs)
        ind = self.getCommBufferByID(cID)
        if ind < 0:
            raise IndexError
        self._sendMessageToIndex(msg, ind, reliable=reliable)

    def broadcast(self, data, reliable=None, **kwargs):
        msg = self._crMessage(data, **kwargs)
        for ind in xrange(len(self.commBuffer)):
            self._sendMessageToIndex(msg, ind, reliable=reliable)

    def _sendDataToIndex(self, data, index, reliable=None, **kwargs):
        msg = self._crMessage(data, **kwargs)
        # print "sending msg: ", msg
        self._sendMessageToIndex(msg, index, reliable=reliable)

    def _sendMessageToIndex(self, message, index, reliable=None):
        if not isinstance(index, collections.Iterable):
            index = [index]
        if type(message)==dict:
            message = [message]
        for msg in message:    
            for ind in index:
                if reliable is None:
                    reliable = self.reliable
                if not reliable:
                    msg[SEQN] = -1
                else:
                    msg[SEQN] = self.commBuffer[ind].addSendMessage(msg, sendtime=self.time.getFrameTime())
                msg[AKN] = self.commBuffer[ind].rseqNumber
                if not msg[MSG_TYPE] == MULT:
                    if msg[ENCODED]:
                        msg[OAKN] = self.encode([m[SEQN] for m in self.commBuffer[ind].recvBuffer])
                    else:
                        msg[OAKN] = [m[SEQN] for m in self.commBuffer[ind].recvBuffer]
                # print "sending to: ", self.commBuffer[ind].id, self.commBuffer[ind].addr.getIpString(), self.commBuffer[ind].addr.getPort()
                self.commBuffer[ind].lastSend = self.time.getFrameTime()
                self.commBuffer[ind].lastAKN = msg[AKN]
                self.sendMessage(msg, self.commBuffer[ind].addr)

    def sendData(self, data, addr, **kwargs):
        msg = self._crMessage(data, **kwargs)
        if not isinstance(addr, collections.Iterable):
            addr = [addr]
        if type(msg)==dict:
            msg = [msg]    
        for address in addr:
            for m in msg:
                self.sendMessage(m, address)

    def _crMessage(self, data, msgtype=0, seqNum=-1, akn=0, oakn={}, out_of_line=False):
        enc_data = self.encode(data)
        if len(enc_data) > self.maxlength:
            chunks = self.chunks(enc_data, self.maxlength)
            nchunks = math.ceil(len(enc_data) / (1.0 * self.maxlength))
            identifier = self.multMsgID
            self.multMsgID += 1
            oakn = [msgtype, identifier, nchunks]
            msgtype = MULT
        else:
            chunks = [enc_data]
            nchunks = 1            

        messages = []
        n = 0
        for dat in chunks:
            msg = {}
            msg[SEQN] = seqNum
            msg[AKN] = akn
            msg[MSG_TYPE] = msgtype
            msg[OOL] = out_of_line
            if nchunks > 1:
                oakn.append(n)
                msg[OAKN] = self.encode(oakn)
                oakn.pop()
                n += 1
            else:
                msg[OAKN] = self.encode(oakn)
            msg[DATA] = dat
            msg[ENCODED] = True
            msg[ADDR] = None
            msg[TIME] = 0
            messages.append(msg)

        return messages

    def _crDatagram(self, msg):
        # create Datagram from message
        myPyDatagram = PyDatagram()
        myPyDatagram.addInt32(msg[SEQN])
        myPyDatagram.addInt32(msg[AKN])
        myPyDatagram.addInt16(msg[MSG_TYPE])
        myPyDatagram.addInt8(msg[OOL])
        if not msg[ENCODED]:
            myPyDatagram.addString(self.encode(msg[OAKN]))
            myPyDatagram.addString(self.encode(msg[DATA]))
        else:
            myPyDatagram.addString(msg[OAKN])
            myPyDatagram.addString(msg[DATA])
        return myPyDatagram

    def _processData(self, netDatagram):
        # convert incoming Datagram to dict
        myIterator = PyDatagramIterator(netDatagram)
        msg = {}
        msg[SEQN] = myIterator.getInt32()
        msg[AKN] = myIterator.getInt32()
        msg[MSG_TYPE] = myIterator.getInt16()
        msg[OOL] = myIterator.getInt8()
        msg[OAKN] = self.decode(myIterator.getString())
        if not msg[MSG_TYPE] == MULT:
            msg[DATA] = self.decode(myIterator.getString())
        else:
            msg[DATA] = (myIterator.getString())
        # msg.append(self.decode(myIterator.getString()))
        return msg

    def getData(self):
        data = []
        while self.cReader.dataAvailable():
            datagram = NetDatagram()  # catch the incoming data in this instance
            # Check the return value; if we were threaded, someone else could have
            # snagged this data before we did
            if self.cReader.getData(datagram):
                # pkg = []
                pkg = self._processData(datagram)
                tmpaddr = datagram.getAddress()
                addr = NetAddress()
                addr.setHost(tmpaddr.getIpString(), tmpaddr.getPort())
                pkg[ADDR] = addr
                data.append(pkg)
        return data

    def addCommBuffer(self, addr):
        cb_id = self.nextID
        self.commBuffer.append(commBuffer(id=cb_id, addr=addr, lastRecv=self.time.getFrameTime()))
        self.nextID += 1
        self.conAddresses = [(cb.addr.getIp(), cb.addr.getPort()) for cb in self.commBuffer]
        self.conIDs = [cb.id for cb in self.commBuffer]
        return cb_id

    def removeCommBuffer(self, cID):
        ind  = self.getCommBufferByID(cID)
        if ind < 0:
            raise IndexError
        del self.commBuffer[ind]
        self.conAddresses = [(cb.addr.getIp(), cb.addr.getPort()) for cb in self.commBuffer]
        self.conIDs = [cb.id for cb in self.commBuffer]

    def chunks(self, string, n):
        return [string[i:i+n] for i in range(0, len(string), n)]

class UDPclient(UDPconnection):
    """
    listens on a given UDP port and connects to a remote server
    """
    def __init__(self, userdata, listenport, serverip, serverport=None, **kwargs):
        if serverport is None:
            self.serverport = listenport
        else:
            self.serverport = serverport
        attempts = 0
        while attempts < MAX_ATTEMPTS:
#            print attempts
            try:
                UDPconnection.__init__(self, port=listenport, **kwargs)
                break
            except:
                listenport += 1
                attempts += 1
                print 'except', listenport, attempts
        else:
            raise Exception('Client could not be started') 
            
        
        self.serverip = serverip
        self.serverAddr = NetAddress()
        self.serverAddr.setHost(self.serverip, self.serverport)
        self.connected = False
        taskMgr.doMethodLater(0.5, self.connect, "Connect", extraArgs=[userdata], appendTask=True)
#        self.connect(userdata)
        self.handlers[SMSG_AUTH_RESPONSE] = self.authenticate
        self.handlers[SMSG_DISCONNECT_ACK] = self.serverdisconnect

    def getPing(self):
        if not self.connected:
            return -1
        ind = self.getCommBufferByID(self.serverID)
        return self.commBuffer[ind].ping

    def getServerCommBuffer(self):
        if not self.connected:
            return 0
        ind = self.getCommBufferByID(self.serverID)
        return self.commBuffer[ind]

    def getCommStatus(self):
        if not self.connected:
            return -1
        ind = self.getCommBufferByID(self.serverID)
        return len(self.commBuffer[ind].sendBuffer)

    def authenticate(self, data, addr):
        if data > 0:
            self.clientID = data
            self.connected = True
            if self.getCommBufferByAddr(addr) >= 0:
                del self.commBuffer[:]
            self.serverID = self.addCommBuffer(addr=addr)

    def send(self, *args, **kwargs):
        self.sendToServer(*args, **kwargs)

    def sendToServer(self, data, **kwargs):
        if self.connected and len(self.commBuffer):
            self.sendDataToID(data, self.serverID, **kwargs)
        else:
            raise Exception('Not Connected')

    def connect(self, userdata, task):
        if not self.connected:
            self.sendData(userdata, self.serverAddr, msgtype=CMSG_AUTH)
            self.logger.info("connect %s", userdata)
            return Task.again
        
    def disconnect(self):
        if self.connected:
            self.send("", msgtype=CMSG_DISCONNECT_REQ, reliable=1)
            self.connected = False

    def serverdisconnect(self, data):
        print "disconnected from server"
        self.connected = False


class UDPserver(UDPconnection):
    """
    handles UDP connections
    """
    def __init__(self, port, **kwargs):
        UDPconnection.__init__(self, port, **kwargs)
#        self.clients = []
#        self.nextclientID = 1
#        taskMgr.add()
        self.handlers[CMSG_AUTH] = self.authenticate
        self.handlers[CMSG_CHAT] = self.sendChat
        self.handlers[CMSG_DISCONNECT_REQ] = self.disconnect
#        taskMgr.doMethodLater(2.0, self.testbroadcast, "test")

    def testbroadcast(self, task):
        data = "Servermessage"
        self.broadcast(data, SMSG_CHAT)
        return Task.again

    def sendChat(self, msg, id=None):
        # print 'chat message received ', msg
        data = (id, msg)
        self.broadcast(data, reliable=1, msgtype=SMSG_CHAT)

    def authenticate(self, data, addr):
        print "Client trying to connect: ", data, self.nextID, addr.getIpString(), addr.getPort()
        ind = self.getCommBufferByAddr(addr)
        if ind < 0:
            print "adding Client"
            cl_id = self.addCommBuffer(addr=addr)
        else:
            print "resend authenticate"
            cl_id = self.commBuffer[ind].id
        data = [cl_id]
        self.sendDataToID(data, cl_id, msgtype=SMSG_AUTH_RESPONSE, reliable=0)
        return cl_id

    def disconnect(self, data, id=None):
        if id is not None:
            print 'client %d disconnected' % id
            self.sendDataToID(data, id, msgtype=SMSG_DISCONNECT_ACK, reliable=0)
            self.removeCommBuffer(id)

    def shutdown(self):
        for cb in self.commBuffer:
            self.disconnect("", id=cb.id)
            

