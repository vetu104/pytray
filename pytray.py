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

script_dir = os.path.dirname(os.path.abspath(sys.argv[0]))


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


def pixmap_to_image(pixmap):
    width, height, argb = pixmap.unpack()[0]
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
    texture = Gdk.Texture.new_for_pixbuf(pixbuf)

    image = Gtk.Image.new_from_paintable(texture)

    return (width, height, image)


def find_icon(item, proxy):
    icon = proxy.get_cached_property("IconName")
    overlayicon = proxy.get_cached_property("OverlayIconName")
    attentionicon = proxy.get_cached_property("AttentionIconName")
    iconpix = proxy.get_cached_property("IconPixmap")
    overlaypix = proxy.get_cached_property("OverlayIconPixmap")
    attentionpix = proxy.get_cached_property("AttentionIconPixmap")
    if icon:
        sicon = icon.get_string()
        logging.debug("Iconfinder returned icon")
        image = Gtk.Image.new_from_icon_name(sicon)
        return image
    # elif attentionicon:
    #     logging.debug("Iconfinder returned attentionicon")
    #     return attentionicon
    elif iconpix:
        logging.debug("Iconfinder returned pixmap")
        image = pixmap_to_image(iconpix)[2]

        return image
    # elif attentionpix:
    #     logging.debug("Iconfinder returned attentionpixmap")
    #     return attentionpix
    else:
        return item.icon
        logging.warning(f"No icon found for {proxy.dbuspath}")


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
        self.menuproxy = None
        print(self.get_child())
        print(self.get_css_classes())

        with open(script_dir + "/Resources/StatusNotifierItem.xml", "r") as f:
            nodeinfo = Gio.DBusNodeInfo.new_for_xml(f.read())
            Gio.DBusProxy.new_for_bus(
                    Gio.BusType.SESSION,
                    Gio.DBusProxyFlags.NONE,
                    nodeinfo.interfaces[0],
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
            # item[2] == submenu ???
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
        self.icon = find_icon(self, proxy)
        self.set_child(self.icon)
        self.menupath = proxy.get_cached_property("Menu").get_string()
        if not self.menupath.startswith(("/org/ayatana/NotificationItem", "/MenuBar", "/com/canonical/dbusmenu")):
            logging.warning(f"unknown dbusmenupath {self.menupath}")
            return
        with open(script_dir + "/Resources/DBusMenu.xml", "r") as f:
            nodeinfo = Gio.DBusNodeInfo.new_for_xml(f.read())
            Gio.DBusProxy.new_for_bus(
                    Gio.BusType.SESSION,
                    Gio.DBusProxyFlags.NONE,
                    nodeinfo.interfaces[0],
                    self.busname,
                    self.menupath,
                    "com.canonical.dbusmenu",
                    None,
                    self.on_menu_ready)
        proxy.connect("g-signal", self.on_signal)
        self.proxy = proxy

    def on_signal(self, proxy, sender, signal, params, userdata=None):
        if signal == "NewIcon":
            self.icon = find_icon(self, proxy)
            self.set_child(self.icon)


class StatusNotifierHost:
    def __init__(self):
        self.proxy = None

    def on_signal(self, proxy, sender, signal, params, userdata=None):
        if signal == "StatusNotifierItemRegistered":
            dbuspath = params[0].split("#")[0]
            dbusobj = params[0].split("#")[1]
            titem = TrayItem(dbuspath, dbusobj)
            app.window.add_item(titem)

        elif signal == "StatusNotifierItemUnregistered":
            dbuspath = params[0].split("#")[0]
            app.window.remove_item(dbuspath)

    def on_proxy_acquired(self, conn, res):
        proxy = conn.new_for_bus_finish(res)
        proxy.call(
                "RegisterStatusNotifierHost",
                GLib.Variant.new_tuple(GLib.Variant.new_string("org.vetu104.Pytray")),
                Gio.DBusCallFlags.NONE,
                -1)
        vnewitems = proxy.get_cached_property("RegisteredStatusNotifierItems")
        newitems = vnewitems.unpack()
        for item in newitems:
            dbuspath, dbusobj = item.split("#")
            titem = TrayItem(dbuspath, dbusobj)
            app.window.add_item(titem)
        proxy.connect("g-signal", self.on_signal)
        self.proxy = proxy

    def start(self):
        with open(script_dir + "/Resources/StatusNotifierWatcher.xml", "r") as f:
            nodeinfo = Gio.DBusNodeInfo.new_for_xml(f.read())
            Gio.DBusProxy.new_for_bus(
                    Gio.BusType.SESSION,
                    Gio.DBusProxyFlags.NONE,
                    nodeinfo.interfaces[0],
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
