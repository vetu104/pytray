#!/usr/bin/env python

import argparse
import logging
import os
import sys
import time
from statusnotifierwatcher import StatusNotifierWatcher
import gi
gi.require_version("Dbusmenu", "0.4")
gi.require_version("Gtk", "4.0")
from gi.repository import GLib  # noqa: E402
from gi.repository import Gio  # noqa: E402
from gi.repository import Gtk  # noqa: E402


parser = argparse.ArgumentParser()
parser.add_argument("-v", action="store_true")
parser.add_argument("-vv", action="store_true")
args = parser.parse_args()
if args.v:
    logging.basicConfig(format="PyTray::%(module)s::%(levelname)s:%(message)s",
                        stream=sys.stderr, level="INFO")
elif args.vv:
    logging.basicConfig(format="PyTray::%(module)s::%(levelname)s:%(message)s",
                        stream=sys.stderr, level="DEBUG")

script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))
f = open(script_dir + "/StatusNotifierItem.xml", "r")
sninode = Gio.DBusNodeInfo.new_for_xml(f.read())
f.close()
f = open(script_dir + "/StatusNotifierWatcher.xml", "r")
snwnode = Gio.DBusNodeInfo.new_for_xml(f.read())
f.close()


class Pytray(Gtk.Application):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.connect("activate", self._on_activate)

    def _on_activate(self, app):
        self.win = MainWindow(application=app)
        self.win.present()


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_title("pytray")
        self.items = []
        self.set_startup_id = "pytray"
        self.set_default_size(28, 28)
        self.set_decorated(False)
        self.set_resizable(False)
        self.box = Gtk.Box.new(Gtk.Orientation.HORIZONTAL, 2)
        self.box.set_vexpand(True)
        self.box.set_hexpand(True)
        self.set_child(self.box)
        self.present()

    def add_item(self, icon):
        logging.debug(f"Adding {icon.busname} to box")
        icon.set_vexpand(True)
        icon.set_hexpand(True)
        self.items.append(icon)
        self.box.append(icon)

    def remove_item(self, dbuspath):
        for item in self.items:
            if item.busname == dbuspath:
                logging.debug(f"Removing {item.busname} from box")
                self.box.remove(item)
                self.items.remove(item)


def icon_from_name(viconname):
    iconname = viconname.get_string()
    icon = Gtk.Image.new_from_icon_name(iconname)
    icon.set_pixel_size(24)
    return icon


def actionbuilder(menu, proxy):
    actiongroup = Gio.SimpleActionGroup.new()
    for item in menu:

        def on_action(self, param, userdata=None):
            proxy.call(
                    "Event",
                    GLib.Variant("(isvu)", (item[0], "clicked", GLib.Variant("s", ""), time.time())),
                    Gio.DBusCallFlags.NONE,
                    -1)

        action = Gio.SimpleAction.new(str(item[0]))
        action.connect("activate", on_action)
        actiongroup.add_action(action)

    return actiongroup


def menubuilder(items, proxy):
    menu = Gio.Menu.new()
    for item in items:
        menuitem = Gio.MenuItem.new(item[1], f"menuclick.{item[0]}")
        menu.append_item(menuitem)
    return menu


class TrayItem(Gtk.MenuButton):
    def __init__(self, dbusname, dbusobj):
        super().__init__()
        self.busname = dbusname

        Gio.DBusProxy.new_for_bus(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.NONE,
                sninode.interfaces[0],
                dbusname,
                dbusobj,
                "org.kde.StatusNotifierItem",
                None,
                self.on_proxy_ready)

    def on_menu_ready(self, obj, token):
        proxy = obj.new_for_bus_finish(token)
        ret = proxy.call_sync(
                "GetLayout",
                GLib.Variant("(iias)", (0, -1, [])),
                Gio.DBusCallFlags.NONE,
                -1)
        layout = ret[1]  # (0, {'children-display': 'submenu'}, [actual menuitems])
        menuitems = layout[2]  # [(id, {"label": "somelabel"}, []), (id, {"label": "somelabel"}, []), ...]
        lst = []
        for item in menuitems:
            if "label" in item[1].keys():
                lst.append((item[0], item[1]["label"]))
        self.actions = actionbuilder(lst, proxy)
        self.insert_action_group("menuclick", self.actions)
        menumodel = menubuilder(lst, proxy)
        popover = Gtk.PopoverMenu.new_from_model(menumodel)
        popover.set_autohide(False)
        popover.set_has_arrow(False)
        self.set_popover(popover)
        self.popover = popover

    def on_proxy_ready(self, obj, token):
        proxy = obj.new_for_bus_finish(token)
        self.icon = icon_from_name(proxy.get_cached_property("IconName"))
        self.set_child(self.icon)
        self.menupath = proxy.get_cached_property("Menu").get_string()
        Gio.DBusProxy.new_for_bus(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.NONE,
                None,
                self.busname,
                self.menupath,
                "com.canonical.dbusmenu",
                None,
                self.on_menu_ready)
        proxy.connect("g-signal", self.on_signal)
        # proxy.connect("g-properties-changed", self.on_properties_changed)
        self.proxy = proxy

    def on_signal(self, proxy, sender, signal, params, userdata=None):
        if signal == "NewIcon":
            self.icon = icon_from_name(self.proxy.get_cached_property("IconName"))
            self.set_child(self.icon)

    # def on_properties_changed(self, proxy, changed_props, inval_props, userdata=None):


class StatusNotifierHost:
    def __init__(self):
        self.proxy = None

    def on_signal(self, proxy, sender, signal, params, userdata=None):
        if signal == "StatusNotifierItemRegistered":
            dbuspath = params[0].split("#")[0]
            dbusobj = params[0].split("#")[1]
            titem = TrayItem(dbuspath, dbusobj)
            app.win.add_item(titem)

        elif signal == "StatusNotifierItemUnregistered":
            dbuspath = params[0].split("#")[0]
            app.win.remove_item(dbuspath)

    def on_proxy_acquired(self, conn, res):
        proxy = conn.new_for_bus_finish(res)
        proxy.call(
                "RegisterStatusNotifierHost",
                GLib.Variant.new_tuple(GLib.Variant.new_string("org.vetu104.Pytray")),
                Gio.DBusCallFlags.NONE,
                -1)
        proxy.connect("g-signal", self.on_signal)
        self.proxy = proxy

    def start(self):
        Gio.DBusProxy.new_for_bus(
                Gio.BusType.SESSION,
                Gio.DBusProxyFlags.NONE,
                snwnode.interfaces[0],
                "org.kde.StatusNotifierWatcher",
                "/StatusNotifierWatcher",
                "org.kde.StatusNotifierWatcher",
                None,
                self.on_proxy_acquired)


if __name__ == "__main__":
    app = Pytray(application_id="org.vetu104.Pytray")
    snwatcher = StatusNotifierWatcher()
    snwatcher.start()
    snhost = StatusNotifierHost()
    snhost.start()
    app.run()
