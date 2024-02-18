#!/usr/bin/env python

import logging
# import argparse
import sys
import os
import gi  # noqa: F401
from gi.repository import GLib
from gi.repository import Gio

# parser = argparse.ArgumentParser()
# parser.add_argument("-v", action="store_true")
# parser.add_argument("-vv", action="store_true")
# args = parser.parse_args()
# if args.v:
#     logging.basicConfig(format="PyTray::watcher::%(levelname)s:%(message)s",
#                         stream=sys.stderr, level="INFO")
# elif args.vv:
#     logging.basicConfig(format="PyTray::watcher:::%(levelname)s:%(message)s",
#                         stream=sys.stderr, level="DEBUG")

script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
f = open(script_dir + "/StatusNotifierWatcher.xml", "r")
NODE_INFO = Gio.DBusNodeInfo.new_for_xml(f.read())
f.close()


class StatusNotifierWatcher:
    def __init__(self):
        self._managed_items = []
        self._owner_id = 0
        self._conn = None
        self._host = None

    def _on_method_call(self, conn, sender, path, interface, method, params, invocation):
        props = {
            "RegisteredStatusNotifierItems": GLib.Variant("as", self._managed_items),
            "IsStatusNotifierHostRegistered": GLib.Variant("b", self._host),
            "ProtocolVersion": GLib.Variant("i", 0),
        }

        if method == "Get" and params[1] in props:
            logging.debug(sender + " called 'Get' on path " + path)
            invocation.return_value(GLib.Variant("(v)", [props[params[1]]]))
            conn.flush()
        elif method == "GetAll":
            logging.debug(sender + " called 'GetAll' on path " + path)
            invocation.return_value(GLib.Variant("(a{sv})", [props]))
            conn.flush()
        elif method == "RegisterStatusNotifierItem":
            # ":1.xxx#/StatusNotifierItem" for sni, ":1.xxx#/org/ayatana/xxx" for ayatana
            if params[0].startswith("/"):
                item = (sender + "#" + params[0])
            else:
                item = (sender + "#" + "/StatusNotifierItem")
            logging.debug(sender + " called " + method + " on path " + path + ". params[0]: " + params[0])
            logging.info("Adding " + str(item) + " to managed items")
            self.add_item(item)
            logging.debug("Managed items:" + str(self._managed_items))
            invocation.return_value(None)
            conn.flush()
        elif method == "RegisterStatusNotifierHost":
            if not self._host:
                self.add_host(params[0])
            else:
                logging.error("StatusNotifierHost already registered")
            invocation.return_value(None)
            conn.flush()

    def _on_signal(self, conn, sender, path, interface, signal, params):
        if signal == "NameOwnerChanged":
            # Host disappeared
            if params[2] == "" and params[0] == self._host:
                logging.info("SNH disappeared, unregistering")
                self._host = False
            # Name has new owner
            if params[2] != "":
                result = ""
                substr = params[0]
                for word in self._managed_items:
                    if substr in word:
                        result = word
                if result != "":
                    objpath = result.split("#")[1]
                    newitem = params[2] + "#" + objpath
                    logging.info("Removing " + result +
                                 " from managed items and adding " + newitem)
                    self.remove_item(result)
                    self.add_item(newitem)
                    logging.debug("Managed items:" + str(self._managed_items))
            # Untrack orphaned item
            elif params[2] == "":
                result = ""
                substr = params[0]
                for word in self._managed_items:
                    if substr in word:
                        result = word
                if result != "":
                    logging.info("Removing " + result + " from managed items")
                    self.remove_item(result)
                    logging.debug("Managed items:" + str(self._managed_items))

    def _on_bus_acquired(self, conn, name):
        self._conn = conn
        interface = NODE_INFO.interfaces[0]

        conn.register_object("/StatusNotifierWatcher", interface, self._on_method_call)

        conn.signal_subscribe(
                None,  # Listen all senders
                "org.freedesktop.DBus",  # Interface
                "NameOwnerChanged",  # Signal
                None,  # Match all paths
                None,  # Match all args
                Gio.DBusSignalFlags.NONE,
                self._on_signal)

    def _on_name_lost(self, conn, name):
        sys.exit(f"Could not acquire {name}.")

    def start(self):
        self.owner_id = Gio.bus_own_name(
                Gio.BusType.SESSION,
                "org.kde.StatusNotifierWatcher",
                Gio.BusNameOwnerFlags.NONE,
                self._on_bus_acquired,
                None,  # on_name_acquired
                self._on_name_lost)

    def stop(self):
        Gio.bus.unown_name(self.owner_id)

    def add_item(self, ipath):
        self._managed_items.append(ipath)
        signal_data = GLib.Variant("(s)", [ipath])
        logging.debug("Emitting signal for add item")
        self._conn.emit_signal(
                None,  # destination_bus_name
                "/StatusNotifierWatcher",  # object_path
                "org.kde.StatusNotifierWatcher",  # interface_name
                "StatusNotifierItemRegistered",  # signal_name,
                signal_data)  # params

    def remove_item(self, ipath):
        if ipath in self._managed_items:
            signal_data = GLib.Variant("(s)", [ipath])
            logging.debug("Emitting signal for remove item")
            self._conn.emit_signal(
                    None,  # destination_bus_name
                    "/StatusNotifierWatcher",  # object_path
                    "org.kde.StatusNotifierWatcher",  # interface_name
                    "StatusNotifierItemUnregistered",  # signal_name,
                    signal_data)  # params
            self._managed_items.remove(ipath)

    def add_host(self, ipath):
        self._host = ipath
        self._conn.emit_signal(
                None,
                "/StatusNotifierWatcher",
                "org.kde.StatusNotifierWatcher",
                "StatusNotifierHostRegistered")
        logging.info("Registered " + ipath + " as current host")

    def get_items(self):
        return self.managed_items


if __name__ == "__main__":
    loop = GLib.MainLoop()
    snwatcher = StatusNotifierWatcher()
    snwatcher.start()
    loop.run()
