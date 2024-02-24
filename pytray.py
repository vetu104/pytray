#!/usr/bin/env python

import argparse
import logging
import os
import sys
import time
from Libs.statusnotifierwatcher import StatusNotifierWatcher
import gi
gi.require_version("Gtk", "4.0")
from gi.repository import GLib  # noqa: E402
from gi.repository import Gio  # noqa: E402
from gi.repository import Gtk  # noqa: E402
from gi.repository import GdkPixbuf  # noqa: E402
from gi.repository import Gdk  # noqa: E402
from gi.repository import GObject  # noqa E402


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
else:
    logging.basicConfig(format="PyTray::%(module)s::%(levelname)s:%(message)s",
                        stream=sys.stderr, level="WARNING")

script_dir = os.path.dirname(os.path.realpath(__file__))
resources_dir = f"{script_dir}/Resources"


# def load_css(app):
#     provider = Gtk.CssProvider.new()
#     provider.load_from_path(script_dir + "/Resources/style.css")
#
#     Gtk.StyleContext.add_provider_for_display(
#         Gdk.Display.get_default(),
#         provider,
#         Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)


class Pytray(Gtk.Application):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.connect("activate", self._on_activate)
        # self.connect("startup", load_css)

    def _on_activate(self, app):
        self.window = MainWindow(application=app)
        self.window.present()


class MainWindow(Gtk.ApplicationWindow):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.set_name("window")
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

    def add_item(self, newitem):
        for item in self.items:
            if item.busname == newitem.busname:
                return
        logging.debug(f"Adding {newitem.busname} to box")
        newitem.set_vexpand(True)
        newitem.set_hexpand(True)
        self.items.append(newitem)
        self.box.append(newitem)

    def remove_item(self, dbuspath):
        for item in self.items:
            if item.busname == dbuspath:
                logging.debug(f"Removing {item.busname} from box")
                self.box.remove(item)
                self.items.remove(item)


def argb_to_rgba(icon_bytes):
    arr = icon_bytes
    for i in range(0, len(arr), 4):
        arr[i: i + 4] = arr[i: i + 4][::-1]

    return arr


class TrayItem(Gtk.Image):
    def __init__(self, busname, busobj):
        super().__init__()
        self._sniproxy = None
        self._menuproxy = None
        self.busname = busname

        self._actiongroup = Gio.SimpleActionGroup.new()
        self._menumodel = None
        self._popovermenu = None
        self._menulayout = None

        self._leftclick = Gtk.GestureClick.new()
        self._leftclick.connect("pressed", self._on_leftclick)
        self._leftclick.set_button(1)
        self.add_controller(self._leftclick)
        self._rightclick = Gtk.GestureClick.new()
        self._rightclick.connect("pressed", self._on_rightclick)
        self._rightclick.set_button(3)
        self.add_controller(self._rightclick)

        self.set_icon_size(Gtk.IconSize.NORMAL)

        with open(f"{resources_dir}/StatusNotifierItem.xml", "r") as f:
            nodeinfo = Gio.DBusNodeInfo.new_for_xml(f.read())
            Gio.DBusProxy.new_for_bus(
                    Gio.BusType.SESSION,
                    Gio.DBusProxyFlags.NONE,
                    nodeinfo.interfaces[0],
                    self.busname,
                    busobj,
                    "org.kde.StatusNotifierItem",
                    None,
                    self._on_sniproxy_ready)

    def _on_leftclick(self, obj, n_press, x, y):
        self._sniproxy.call(
                "Activate",
                GLib.Variant("(ii)", [0, 0]),
                Gio.DBusCallFlags.NONE,
                -1)

    def _on_rightclick(self, obj, n_press, x, y):
        self._menuproxy.call(
                "AboutToShow",
                GLib.Variant("(i)", [0]),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
                self._on_menushow)

    def _on_menushow(self, obj, res):
        try:
            needUpdate = obj.call_finish(res).unpack()[0]
            if needUpdate is True:
                self._update_menu()
        except gi.repository.GLib.GError:
            pass

        self._popovermenu.popup()

    def _on_sniproxy_ready(self, obj, result):
        self._sniproxy = obj.new_for_bus_finish(result)

        self._find_icon()

        self._sniproxy.connect("g-signal", self._on_snisignal)

        known_menuobjects = (
                "/MenuBar",
                "/com/canonical/dbusmenu",
                "/org/ayatana/NotificationItem")

        invalid_menuobjects = ("/NO_DBUSMENU")

        menubusobj = self._sniproxy.get_cached_property(
                "Menu").get_string()

        if menubusobj.startswith(invalid_menuobjects):
            return
        if not menubusobj.startswith(known_menuobjects):
            logging.warning(f"Unknown Dbusmenu object: {self.menubusobj}")
            return

        with open(f"{resources_dir}/DBusMenu.xml", "r") as f:
            nodeinfo = Gio.DBusNodeInfo.new_for_xml(f.read())
            Gio.DBusProxy.new_for_bus(
                    Gio.BusType.SESSION,
                    Gio.DBusProxyFlags.NONE,
                    nodeinfo.interfaces[0],
                    self.busname,
                    menubusobj,
                    "com.canonical.dbusmenu",
                    None,
                    self._on_menuproxy_ready)

    def _find_icon(self):
        iconname = self._sniproxy.get_cached_property("IconName")
        # overlayicon = proxy.get_cached_property("OverlayIconName")
        # attentionicon = proxy.get_cached_property("AttentionIconName")
        iconpix = self._sniproxy.get_cached_property("IconPixmap")
        # overlaypix = proxy.get_cached_property("OverlayIconPixmap")
        # attentionpix = proxy.get_cached_property("AttentionIconPixmap")
        if iconname:
            self._iconname = iconname.get_string()
            self._texture = None

            self.set_from_icon_name(self._iconname)
        # elif attentionicon:
        #     logging.debug("Iconfinder returned attentionicon")
        #     return attentionicon
        elif iconpix:
            width, height, argb = iconpix.unpack()[0]
            rgba = argb_to_rgba(argb)

            size = len(rgba)
            padding = size / width - 4 * width
            rowstride = 4 * width + padding

            gbytes = GLib.Bytes.new(argb)
            pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(
                    gbytes,
                    GdkPixbuf.Colorspace.RGB,
                    True,
                    8,
                    width,
                    height,
                    rowstride)

            self._texture = Gdk.Texture.new_for_pixbuf(pixbuf)
            self._iconname = None

            self.set_from_paintable(self._texture)
        # elif attentionpix:
        #     logging.debug("Iconfinder returned attentionpixmap")
        #     return attentionpix
        else:
            return

    def _on_snisignal(self, proxy, sender, signal, params, userdata=None):
        if signal == "NewIcon":
            self._find_icon()

    def _on_menuproxy_ready(self, obj, result):
        self._menuproxy = obj.new_for_bus_finish(result)

        self._menuproxy.call(
                "GetLayout",
                # parentid, depth(-1=all), props([]=all)
                GLib.Variant("(iias)", (0, -1, [])),
                Gio.DBusCallFlags.NONE,
                -1,
                None,
                self._on_menulayout_ready)

        self._menuproxy.connect("g-signal", self._on_menusignal)

    def _on_menusignal(self, proxy, sender, signal, params):
        if signal == "ItemsPropertiesUpdated" or signal == "LayoutUpdated":
            self._menuproxy.call(
                    "GetLayout",
                    # parentid, depth(-1=all), props([]=all)
                    GLib.Variant("(iias)", (0, -1, [])),
                    Gio.DBusCallFlags.NONE,
                    -1,
                    None,
                    self._on_menulayout_ready)

    def _on_menulayout_ready(self, obj, result):
        try:
            self._menulayout = obj.call_finish(result)
            self._update_menu()
        except gi.repository.GLib.GError:
            pass

    def _update_menu(self):
        self._popovermenu = None
        self._menumodel = None
        self._menumodel = Gio.Menu.new()
        self._menurevision, menuprops = self._menulayout
        rootid, _, rootprops = menuprops
        for item in rootprops:
            if ("visible" in item[1].keys()) and (item[1]["visible"] is False):
                continue

            if ("enabled" in item[1].keys()) and (item[1]["enabled"] is False):
                continue

            if "label" in item[1].keys():
                self._menumodel.append(item[1]["label"], f"menuclick.{item[0]}")
                action = self._createaction(item)
                if self._actiongroup.lookup_action(str(item[0])) is None:
                    self._actiongroup.add_action(action)

        self._popovermenu = Gtk.PopoverMenu.new_from_model(self._menumodel)
        self._popovermenu.set_has_arrow(False)
        self._popovermenu.set_parent(self)

        self.insert_action_group("menuclick", self._actiongroup)

    def _createaction(self, item):
        action = Gio.SimpleAction.new(str(item[0]))

        def on_action(actionobj, param):
            self._menuproxy.call(
                    "Event",
                    GLib.Variant("(isvu)", (item[0], "clicked", GLib.Variant("s", ""), time.time())),
                    Gio.DBusCallFlags.NONE,
                    -1)

        action.connect("activate", on_action)

        return action


class StatusNotifierHost:
    def __init__(self):
        self._snwproxy = None

    def start(self):
        with open(f"{resources_dir}/StatusNotifierWatcher.xml", "r") as f:
            nodeinfo = Gio.DBusNodeInfo.new_for_xml(f.read())
            Gio.DBusProxy.new_for_bus(
                    Gio.BusType.SESSION,
                    Gio.DBusProxyFlags.NONE,
                    nodeinfo.interfaces[0],
                    "org.kde.StatusNotifierWatcher",
                    "/StatusNotifierWatcher",
                    "org.kde.StatusNotifierWatcher",
                    None,
                    self._on_proxy_acquired)

    def _on_proxy_acquired(self, conn, res):
        self._snwproxy = conn.new_for_bus_finish(res)

        self._snwproxy.call(
                "RegisterStatusNotifierHost",
                GLib.Variant("(s)", ["org.vetu104.Pytray"]),
                Gio.DBusCallFlags.NONE,
                -1)

        self._snwproxy.connect("g-signal", self._on_signal)

        initial_items = self._snwproxy.get_cached_property(
                "RegisteredStatusNotifierItems").unpack()

        for item in initial_items:
            busname, busobj = item.split("#")
            trayitem = TrayItem(busname, busobj)
            app.window.add_item(trayitem)

    def _on_signal(self, proxy, sender, signal, params, userdata=None):
        if signal == "StatusNotifierItemRegistered":
            busname = params[0].split("#")[0]
            busobj = params[0].split("#")[1]
            trayitem = TrayItem(busname, busobj)
            app.window.add_item(trayitem)

        elif signal == "StatusNotifierItemUnregistered":
            busname = params[0].split("#")[0]
            app.window.remove_item(busname)


if __name__ == "__main__":
    app = Pytray(application_id="org.vetu104.Pytray")
    snwatcher = StatusNotifierWatcher()
    snwatcher.start()
    snhost = StatusNotifierHost()
    snhost.start()
    app.run()
