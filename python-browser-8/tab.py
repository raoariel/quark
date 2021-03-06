#!/usr/bin/env python

# Quark is Copyright (C) 2012-2015, Quark Team.
#
# You can redistribute and modify it under the terms of the GNU GPL,
# version 2 or later, but it is made available WITHOUT ANY WARRANTY.
#
# For more information about Quark, see our web site at:
# http://goto.ucsd.edu/quark/


import os
import stat
import urllib
import inspect
import time
import string
import cStringIO as StringIO
import cPickle as pickle
import time
import sys
import os
import tempfile
import gobject
import threading
import gtk 
from gtk import keysyms
import webkit 
import urlparse
import msg
import ctypes
import socket
import shm
import random
import opt
import re
import struct
import signal
import threading
import select
import quarkexec

gtk.gdk.threads_init()

rrender=True
damage_working=True

def signal_handler(signal, frame):
    #shm.remove_memory(tab.shm_obj.shmid)
    #shm.remove_semaphore(tab.sem_obj.semid)
    global tab
    tlog("shared objects are destroyed:start")
    try :
        shm.remove_semaphore(tab.sem_obj.semid)
    except :
        tlog("an error occured while destroying the semaphore" + str(sys.exc_info()))
        pass
    try :
        try :
            tab.shm_obj.detach()
        except :
            pass

        shm.remove_memory(tab.shm_obj.shmid)
    except :
        tlog("an error occured while destroying the shared memory" + str(sys.exc_info()[0]))
        pass

    tlog("shared objects are destroyed:end")
    sys.exit(0)

def tlog(str):
    tlog_nonl(str + "\n")

def tlog2(str):
    tlog_nonl(str + "\n")

def tlog_nonl(str):
    sys.stderr.write("T: " + str)
    sys.stderr.flush()

def same_orig(url1, url2):
    p1 = urlparse.urlparse(url1)
    p2 = urlparse.urlparse(url2)
    return (p1.scheme == p2.scheme) & (p1.netloc == p2.netloc)

# mostly copied from shm_wrapper.py
def create_memory(size, permissions = 0600):
    """ Creates a new shared memory segment. One can destroy it either
    by calling the module-level method remove_memory() or by calling
    the .remove() method of a handle to said memory.
    """
    memory = None

    while not memory:
        key = random.randint(1, sys.maxint - 1)
        try:
            memory = shm.create_memory(key, size, permissions)
            # for output process
            memory.setuid(quarkexec.quark_output_uid)
        except shm.error, ExtraData:
            tlog("unexpected error:" + str(sys.exc_info()))
            if shm.memory_haskey(key):
                pass
            else:
                raise shm.error, ExtraData
    return memory


class Tab:
    tab_origin = ""
    time = None
    progress = 0
    renderred = False
    area = None
    shm_obj = None
    sem_obj = None

    whitelist = {
        "google.com":"gstatic.com",
        "facebook.com":"fbcdn.net",
        "youtube.com":"ytimg.com",
        "yahoo.com":"yimg.com",
        "wikipedia.org":"wikimedia.org",
        "twitter.com":"twimg.com",
        "accounts.google.com":"gstatic.com",
        "ebay.com":"ebaystatic.com"}

    def write_message(self, m):
        #tlog("BEGIN]write_message is called")
        #tlog(">> " + str(m))
        #stime = time.time()
        msg.write_message_soc(m, self.soc)
        #tlog("END]write_message is finished:%f" % (time.time() - stime))


    def read_message(self):        
        #tlog("BEGIN]read_message is called")
        #stime = time.time()
        m = msg.read_message_soc(self.soc)
        #tlog("<< " + str(m))
        #tlog("END]read_message is finished:%f" % (time.time() - stime))
        return m

    def get_origin(self, uri) :
        p1 = urlparse.urlparse(uri)
        return p1.scheme + "://" + p1.netloc

    def is_tab_sub_origin(self, origin) :
        p1 = urlparse.urlparse(origin)
        return str(p1.netloc).endswith(self.tab_origin)

    def is_sub_origin(self, origin, uri) :
        p1 = urlparse.urlparse(uri)
        return str(p1.netloc).endswith(origin)

    def resource_load_failed(self) :
        tlog("resource loading is failed : " + self.get_uri())

    def resource_cb(self, view, frame, resource, request, response):
        try :
            uri = request.get_uri()
            fname = frame.get_name()
            #tlog('resource-request-starting for ' + str(fname) + " : " + str(uri))
        except Error:
            tlog('resource-request-starting for something weird:this is redirected to webkit')
            return

        if string.find(uri, "http") != 0: 
            # tlog("strange url:" + uri)
            # DON: this is going to result in segmentation fault in libsoup
            # in case that the url is outside of the tab domain.
            # We have to deal with this in a better way.
            return

        # First resource loading in this frame. even navigation
        # callback wasn't called for this frame is this only for the
        # main frame?
        if string.find(str(frame.get_load_status()), "PROVISIONAL") >= 0:
            self.frames[frame] = self.get_origin(uri)
            if self.time == None:
                self.time = time.time()
                self.finishedCnt = 0
                # if the redirection is to an origin that belongs to the tab origin, it's allowed for
                # socket connection

            if self.is_tab_sub_origin(self.frames[frame]) == True:
                #tlog("a frame is navigated to :" + uri + " within the tab origin :" + self.tab_origin)
                return
            else:
                #tlog("a frame is navigated to :" + uri + " outside the tab origin :" + self.tab_origin)
                # main frame is navigated to another domain
                # then, this tab should die by sending navigate message
                if frame == view.get_main_frame() :
                    # This must not be taken.
                    # since the navigation action is handled by
                    # navigation_cb().
                    tlog("FATAL ERROR: the main frame is terminated by navigating to " + uri + " from " + self.tab_origin)
                    m = msg.create_navigate(uri)
                    self.write_message(m)
                    #view.load_uri("about:blank")
                    request.set_uri("about:blank")
                    # this will cause segmentation fault. Because
                    # libsoup's going to try to get a web socket from
                    # the kernel, and it is going to fail.  this
                    # socket conneciton will be refused by the kernel
                    return 
                else :
                    # if it's not the main frame, we let it through wget
                    pass
        
        if self.is_tab_sub_origin(uri) :
            # if this request is within the tab's origin, it's allowed for socket conneciton
            # tlog(uri + " is within the tab origin : " + self.tab_origin)
            return

        if self.tab_origin in self.whitelist :
            #tlog(uri + " is within the whitelistn : " + self.whitelist[self.tab_origin])
            if self.is_sub_origin(self.whitelist[self.tab_origin], str(uri)):
                return

            if self.tab_origin =="youtube.com":
                if (self.is_sub_origin("gstatic.com", str(uri))) : 
                    return
                if (self.is_sub_origin("google.com", str(uri))) : 
                    return

            if self.tab_origin == "ebay.com":
                if (self.is_sub_origin("ebayimg.com", str(uri))) : 
                    return
                if (self.is_sub_origin("ebayrtm.com", str(uri))) : 
                    return

            if self.tab_origin == "blogger.com":
                if (self.is_sub_origin("blogspot.com", str(uri))) : 
                    return
                if (self.is_sub_origin("gstatic.com", str(uri))) : 
                    return
                if (self.is_sub_origin("googleusercontent.com", str(uri))) : 
                    return

        #tlog('FROM FILE ' + fname + " : " + uri)
        #tlog("FROM FILE : 1")
        m = msg.create_req_uri_follow(uri)
        self.write_message(m)
        #tlog("FROM FILE : 2")
        to_process = []
        m = self.read_message()
        while m.type != msg.mtypes.RES_URI:
            #tlog("to process: " + str(m))
            to_process = to_process + [m]
            m = self.read_message()

        #assert(not m.content.startswith("QUARK_REDIRECT"))
        tf = tempfile.NamedTemporaryFile(delete=False)
        tf.write(m.content)
        tf_name = tf.name
        tf.close()

        for m in to_process:
            self.process_message(m)

        request.set_uri('file://' + tf_name)

    def progress_cb(self, view, progress):
        #tlog('PROGRESS: ' + str(view.get_progress()))        
        if view.get_progress() > self.progress + 0.05:
            #self.render()
            self.progress = view.get_progress()

        if view.get_progress() >= 1:
            self.progress = 0
            #tlog2('PAGING LOADING TIME:' +  str(self.finishedCnt) + ":" + self.tab_origin + ":" +str(time.time() - self.time))
            self.finishedCnt = self.finishedCnt + 1
            global rrender
            if rrender <> True:
                self.delayed_render()

            #gtk.timeout_add(200, self.delayed_render)
            #gtk.timeout_add(0, self.delayed_render)
            #self.render()
        
    def navigation_cb(self, view, frame, request, action, policy):
        uri = request.get_uri()
        if frame == view.get_main_frame() and (not self.is_tab_sub_origin(self.get_origin(uri))) :
            tlog('NAV: ' + frame.get_name() + " is navigating to " + uri)
            m = msg.create_navigate(uri)
            self.write_message(m)
            policy.ignore()
            return

    def create_web_view_cb(self, view, frame) : 

        def tresource_cb(view, frame, resource, request, response):
            tlog("temporary view's resource callback is called.")
            request.set_uri("about:blank")

            
        def tnavigation_cb(view, frame, request, action, policy):
            tlog("temporary view's navigation callback is called.")
            uri = request.get_uri()
            m = msg.create_navigate(uri)
            self.write_message(m)
            policy.ignore()
            request.set_uri("about:blank")
            view.destroy()
            frame.stop_loading()
            return
            
        uri = frame.get_uri()
        tlog('NEW WINDOW IS CREATED' + str(uri))

        tview = webkit.WebView()
        tview.connect('navigation-policy-decision-requested', tnavigation_cb)
        tview.connect('resource-request-starting', tresource_cb)
        settings = tview.get_settings()
        settings.set_property("enable-plugins", False)
        return tview

        #m = msg.create_navigate(uri)
        #self.write_message(m)

    #def navigation_request_cb(self, view, frame, request):
    #    uri = request.get_uri()
    #    tlog('navigation_request_cb is called' + str(uri) + "," + str(self.frames[frame]))
    #    return
            
    # def load_status_cb(self, view, status):
    #     #tlog('LOAD-STATUS: ' + str(view.get_load_status()))
    #     if view.get_load_status() == webkit.LOAD_FINISHED:
    #         self.render()

    #def iterated_render(self):
    #    self.render()
    #    gtk.timeout_add(200, self.iterated_render)
    #    return False
            
    def delayed_render(self):
        #tlog("DELAY_RENDER:Delayed_render is called")
        view = self.view
        win = view.get_window()
        (x,y,width,height,depth) = win.get_geometry()
        self.render(x,y,width,height)
        return False

    def delayed_terminate(self):
        sys.exit(0)
        return False

    def render(self,x,y,width,height):
        #stime = time.time()
        self.write_webkit_as_png(x,y,width,height)
        m = msg.create_display_shm(self.shm_obj.shmid, self.shm_size)
        self.write_message(m)
        self.renderred = True
        #tlog("RENDER:renderring has been finished : duraing:" + str(time.time() - stime))

    # real rendering process
    def write_webkit_as_png(self, x,y,width,height):
        stime = time.time()
        view = self.view
        win = view.get_window()
        #(x,y,width,height,depth) = win.get_geometry()
        #pixbuf = self.pixbuf
        pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB,False,8,width,height)
        #pixbuf.get_from_drawable(win,view.get_colormap(),0,0,0,0,width,height)
        #pixbuf = self.pixbuf
        pixbuf.get_from_drawable(win,view.get_colormap(),x,y,0,0,width,height)
        #pixbuf.get_from_drawable(win,view.get_colormap(),x,y,0,0,width,height)
        #pixbuf.get_from_drawable(win,view.get_colormap(),0,0,0,0,1100, 700)
        #pixbuf = self.win.get_pixbuf()
        #tpixbuf.copy_area(x,y,width,height, self.pixbuf, x,y)
        #pixbuf = self.pixbuf
        
        #self.shm_size = 4
        self.shm_size = 4 * 5 # shm_size, x, y, width, height
        def pixbuf_save_func(buf, data=None):
            self.shm_obj.write(buf, self.shm_size)
            self.shm_size = self.shm_size + len(buf)
            return True
        
        #self.sem_obj.setblocking(True)
        self.sem_obj.P()

        try :
            pixbuf.save_to_callback(pixbuf_save_func, 'png')
            self.shm_obj.write(struct.pack("i", self.shm_size-4*5), 4*0)
            self.shm_obj.write(struct.pack("i", x), 4*1)
            self.shm_obj.write(struct.pack("i", y), 4*2)
            self.shm_obj.write(struct.pack("i", width), 4*3)
            self.shm_obj.write(struct.pack("i", height), 4*4)

        # try :
        #     pixels = pickle.dumps(pixbuf.get_pixels_array())
        #     tlog("PIXEL SIZE:%d" % len(pixels))
        #     self.shm_obj.write(struct.pack("i", len(pixels)), 4*0)
        #     self.shm_obj.write(struct.pack("i", x), 4*1)
        #     self.shm_obj.write(struct.pack("i", y), 4*2)
        #     self.shm_obj.write(struct.pack("i", width), 4*3)
        #     self.shm_obj.write(struct.pack("i", height), 4*4)
        #     self.shm_obj.write(pixels , 4*5)
        finally :
            self.sem_obj.V()
            pass
        #self.sem_obj.setblocking(False)

        #pixbuf.save_to_callback(pixbuf_save_func, 'jpeg', {"quality":"50"})
        #tlog("elapsed time for rendering : " + str(time.time() - stime))
        return 

    def handle_input(self, source, condition):
        sys.stderr.flush()
        # before handling an input, check whether there's any enqueued message from libsoup 
        # BEGIN
        while libsoup.quark_queue_idx() >= 0:
            #tlog("libsoup has a queued message!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!11")
            class quark_message(ctypes.Structure):
                pass
            quark_message._fields_=[("msg_id",ctypes.c_char),("param",ctypes.c_char * 512)]
            m = quark_message()
            libsoup.quark_dequeue_msg(ctypes.pointer(m))

            if ord(m.msg_id) == 5 :
                q_m = msg.create_key_press(m.param[0])
                self.process_message(q_m)
            else:
                pass            
            #tlog(str(quark_message_struct))
        # END
        m = self.read_message()
        self.process_message(m)
        gobject.io_add_watch(self.soc.fileno(), gobject.IO_IN, self.handle_input)
        return False

    def delayed_mouse_release(self, m):
        e = gtk.gdk.Event(gtk.gdk.BUTTON_RELEASE)
        e.button = 1
        e.x = float(m.x)
        e.y = float(m.y)
        e.window = self.view.get_window()
        self.view.emit("button_release_event", e)
        #gtk.timeout_add(200, self.delayed_render)
        
    def process_message(self, m):
        if m.type == msg.mtypes.GO:
            self.view.open(m.uri)
        elif m.type == msg.mtypes.RENDER:
            #gtk.timeout_add(0, self.delayed_render)
            #self.render()
            m = msg.create_display_shm(self.shm_obj.shmid, 0)
            self.write_message(m)
            # this is a render msg triggered by tab switching.
            # so we have to render the entire screen again.
            if self.renderred:
                gtk.timeout_add(50, self.delayed_render)
        elif m.type == msg.mtypes.K2T_SET_COOKIE:
            #tlog("<< K2T_SET_COOKIE msg is received:" + m.cookie)
            libsoup.soup_add_invalidated_cookie(ctypes.c_char_p(m.cookie));
            #libsoup.soup_add_invalidated_cookie(ctypes.create_string_buffer(m.cookie));
        elif m.type == msg.mtypes.MOUSE_CLICK:
            e = gtk.gdk.Event(gtk.gdk.BUTTON_PRESS)
            e.button = 1
            e.x = float(m.x)
            e.y = float(m.y)
            e.window = self.view.get_window()
            self.view.emit("button_press_event", e)
            gtk.timeout_add(5, self.delayed_mouse_release, m)

        # elif m.type == msg.mtypes.MOUSE_PRESSED: e =
        #     gtk.gdk.Event(gtk.gdk.BUTTON_PRESS) e.button = m.button
        #     e.x = m.x - 100 e.y = m.y - 100 e.window =
        #     self.view.get_window()
        #     self.view.emit("button_press_event", e) elif m.type ==
        #     msg.mtypes.MOUSE_RELEASED: e =
        #     gtk.gdk.Event(gtk.gdk.BUTTON_RELEASE) e.button =
        #     m.button e.x = m.x - 100 e.y = m.y - 100 e.window =
        #     self.view.get_window()
        #     self.view.emit("button_release_event", e)
        #     gtk.timeout_add(500, self.delayed_render) keycode:
        #     http://rachel-codebook.googlecode.com/svn-history/r130/trunk/Graphics/GraphicsA1/src/appwindow.cpp
        # http://www.pberndt.com/Programme/Linux/pqiv/_download/pqiv.py?ct=raw
        elif m.type == msg.mtypes.KEY_PRESS:
            #tlog("pressed key:" + str(m.key) + "\n")
            if self.escaped == None:
                if m.key == "\\":
                    self.escaped = ""
                else:
                    e = gtk.gdk.Event(gtk.gdk.KEY_PRESS)
                    e.window = self.view.get_window()
                    #tlog("pressed key:" + str(ord(m.key)) + "\n")

                    if ord(m.key) == 19:
                        e.keyval = int(keysyms.Page_Up)
                        e.hardware_keycode = gtk.gdk.keymap_get_default().get_entries_for_keyval(int(keysyms.Page_Up))[0][0]
                    elif ord(m.key) == 20:
                        e.keyval = int(keysyms.Page_Down)
                        e.hardware_keycode = gtk.gdk.keymap_get_default().get_entries_for_keyval(int(keysyms.Page_Down))[0][0]
                    elif ord(m.key) == 8:
                        e.keyval = int(keysyms.BackSpace)
                        e.hardware_keycode = gtk.gdk.keymap_get_default().get_entries_for_keyval(int(keysyms.BackSpace))[0][0]
                    elif ord(m.key) == 9:
                        e.keyval = int(keysyms.Tab)
                        e.hardware_keycode = gtk.gdk.keymap_get_default().get_entries_for_keyval(int(keysyms.Tab))[0][0]
                    elif ord(m.key) == 10:
                        e.keyval = int(keysyms.Return)
                        e.hardware_keycode = gtk.gdk.keymap_get_default().get_entries_for_keyval(int(keysyms.Return))[0][0]
                    else :
                        e.keyval = ord(m.key)
                    
                    self.view.emit("key_press_event", e)
                    #gtk.timeout_add(200, self.delayed_render)
            else:
                if m.key == "\n":
                    self.process_escaped(self.escaped)
                    self.escaped = None
                else:
                    self.escaped += m.key
        elif m.type == msg.mtypes.EXIT:
            gtk.main_quit()
                    
    def add_http(self,url) :
        if re.match("[a-zA-Z]+://.*", url) == None :
            return "http://" + url
        return url

    def process_escaped(self, s):
        if s[0] == "g":
            self.view.open(self.add_http(s[2:]))
            m = msg.create_display_shm(self.shm_obj.shmid, 0)
            self.write_message(m)


    def handle_hup(self, source, condition):
        gtk.main_quit()
        return False

    def damage(self, widget, event):
        if self.area == None :
            tlog("damage is not supposed to be called before expose()")
        area = self.area
        self.area = None

        global damage_working
        global rrender
        if rrender == True and damage_working == True:
            self.render(area.x, area.y, area.width, area.height)

    # this area should be an array.

    def expose(self, widget, event):
        if self.area <> None :
            tlog("expose() : area is not null : not yet processed by damage()")

        self.area = event.area

        global damage_working
        global rrender
        if rrender == True and damage_working == False:
            area = self.area
            self.render(area.x, area.y, area.width, area.height)
            self.area = None

        #area = self.area
        #self.render(area.x, area.y, area.width, area.height)
        #self.area = None

    def main(self):
        #tlog("tab is initiated")
        #fstat = os.stat(sys.argv[0])
        #os.seteuid(fstat[stat.ST_UID])
        #opt.parse_options(sys.argv[4:])

        # opt.parse_options(["-l","-m","-k"])
        # tlog("tab argv:" + str(sys.argv))
	
	libsoup.soup_set_t2k_raw_socket(int(sys.argv[1]))
	#if  opt.options.use_kcookies:
        # cookie cache is always on.
        libsoup.soup_set_kcookies_flag(1)

        self.soc = socket.fromfd(int(sys.argv[1]), msg.FAMILY, msg.TYPE)
        self.soc.setblocking(1)

        self.shm_obj = create_memory(5000000)
        self.shm_obj.attach()
        self.sem_obj = shm.create_semaphore(self.shm_obj.shmid, 1)
        self.sem_obj.setperm(0600)
        self.sem_obj.setuid(quarkexec.quark_output_uid)
        self.sem_obj.setblocking(True)

        self.escaped = None
        
        gobject.io_add_watch(self.soc.fileno(), gobject.IO_IN, self.handle_input)
        gobject.io_add_watch(self.soc.fileno(), gobject.IO_HUP, self.handle_hup)

        self.view = webkit.WebView()
        self.view.connect('expose-event', self.expose)
        self.view.connect('resource-request-starting', self.resource_cb)
        self.view.connect('notify::progress', self.progress_cb)
        self.view.connect('navigation-policy-decision-requested', 
                          self.navigation_cb)
        self.view.connect('create-web-view', 
                          self.create_web_view_cb)
        
        #self.view.connect('notify::load-status', self.load_status_cb)

        settings = self.view.get_settings()
        settings.set_property("enable-plugins", False)

        self.frames = {}
        win = gtk.OffscreenWindow()
        win.set_default_size(1100,700)
        win.add(self.view)
        win.connect('damage-event', self.damage)
        win.show_all()
        self.win = win
        (x,y,width,height,depth) = self.view.get_window().get_geometry()
        self.pixbuf = gtk.gdk.Pixbuf(gtk.gdk.COLORSPACE_RGB,False,8,width,height)


        self.tab_origin = sys.argv[2]

        m = msg.create_display_shm(self.shm_obj.shmid, 0)
        self.write_message(m)
        self.view.open(self.add_http(self.tab_origin))

        #gtk.timeout_add(50, self.iterated_render)

        #self.rthread = threading.Thread(target=self.drawing_thread, args=())
        #self.rthread.start()

        #t_thread = threading.Thread(target=self.input_thread, args=())
        #t_thread.start()
        gtk.main()


libsoup = ctypes.CDLL('libsoup-2.4.so.1')
libgobject = ctypes.CDLL('libgobject-2.0.so')
libwebkit = ctypes.CDLL('libwebkitgtk-1.0.so.0')
session = libwebkit.webkit_get_default_session()
libgobject.g_object_set(session, "enable-plugins", False, None)
# session = libwebkit.webkit_get_default_session()
#libgobject.g_object_set(session, "proxy-uri", proxy_uri, None)
# session = libwebkit.webkit_get_default_session()
# session.get_feature()

tab = Tab()
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGABRT, signal_handler)

tab.main()
