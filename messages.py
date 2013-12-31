#
#Manages onscreen messages
#
from direct.gui.DirectGui import *
from panda3d.core import *
from direct.task import Task


class message:
    """
    Message Class, when passed to messageManger it shows text,
    that will fade out after a given time
    """
    def __init__(self, txt='', sender='system',color=(0, 0, 1.0, 1.0), fadetime=10.0, name='message'):
        self.textnode = TextNode(name)
        self.textnode.setTextColor(color)
        if sender is not '':
            sender = str(sender) + ": "
        self.textnode.setText(str(sender)+"\1SetColor\1"+str(txt)+"")
        self.textnode.setAlign(TextNode.ALeft)
        self.textnode.setShadow(0.05)
        self.textnode.setShadowColor(1, 1, 1, 0.8)
        self.fadeTime = fadetime
        self.createTime = 0
        self.NodePath = None


class messageManager:
    """
    Handler to show and hide messages passed to him on the screen
    """
    def __init__(self, scale=0.05, bottom=0.5, maxheight=1.0, msghandler=None, color=(0, 0, 0, 1.0)):
        self.messages = []
        self.oldmessages = []
        self.scale = scale
        self.bottom = bottom
        self.height = 0
        self.maxheight = maxheight
        if msghandler == None:
            self.msghandler = self.addText
        else:
            self.msghandler = msghandler
        self.textfield = DirectEntry(text="", scale=self.scale, command=self.commit,
                                     initialText="", numLines=1, focus=1, width=50, pos=(0.05, 0, self.bottom))
        self.textfield.reparentTo(hidden)
        self.textfield.visible = 0
        taskMgr.add(self.handler, "Message Handler")

        #change color inside textNodes
        tpMgr = TextPropertiesManager.getGlobalPtr()
        tpSetColor = TextProperties()
        tpSetColor.setTextColor(color)
        tpMgr.setProperties("SetColor", tpSetColor)


    def showtextfield(self):
    # toggle visibility of the entry field and old messages
        if self.textfield.visible:
            self.textfield.reparentTo(hidden)
            self.textfield.visible = 0
            for m in self.oldmessages:
                m.NodePath.reparentTo(hidden)
                m.visible = 0
        else:
            self.textfield.reparentTo(base.a2dBottomLeft)
            self.textfield.visible = 1
            self.textfield['focus'] = True

    def addMessage(self, mes):
        self.messages.append(mes)

    def commit(self, *args, **kwargs):
        self.msghandler(*args, **kwargs)
        self.textfield.enterText('')

    def addText(self, txt, **kwargs):
        if txt == "" or "\\" in txt:
            return
        mes = message(txt, **kwargs)
        self.addMessage(mes)
        # self.textfield.enterText('')

    def handler(self, task):
    # when added to taskMgr (which happens in __init__) this displays new messages
    # and fades out old ones (by moving them to oldmessages).
        messagelist = []
        if self.textfield.visible:
            messagelist = self.oldmessages[:]
        messagelist.extend(self.messages[:])
        self.height = self.scale
        for m in reversed(messagelist):
            if m.createTime == 0:
                m.createTime = task.time
                m.NodePath = base.a2dBottomLeft.attachNewNode(m.textnode)
                m.visible = 1
                m.NodePath.setScale(0.05)
            elif self.textfield.visible and not m.visible:
                m.NodePath.reparentTo(base.a2dBottomLeft)
                m.visible = 1

            self.height += m.textnode.getHeight() * self.scale
            m.NodePath.setPos(0.05, 0, self.bottom + self.height)
            if task.time - m.createTime > m.fadeTime and not self.textfield.visible:
                m.NodePath.reparentTo(hidden)
                m.visible = 0
                self.oldmessages.append(m)
                self.messages.remove(m)
            if self.height > self.maxheight:
                    break
        return Task.cont
