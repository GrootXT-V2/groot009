"""The buddy's window on Mac, using Apple's own AppKit (through PyObjC).

A borderless, see-through window that floats above other windows. Only the
buddy is drawn; clicks on the empty parts go through to whatever is behind.
"""

import AppKit
from AppKit import (
    NSAffineTransform,
    NSApplication,
    NSAttributedString,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSEvent,
    NSFont,
    NSGraphicsContext,
    NSMenu,
    NSMenuItem,
    NSMutableParagraphStyle,
    NSScreen,
    NSTimer,
    NSView,
    NSWindow,
)
from Foundation import NSMakeRect, NSObject, NSRunLoop

from .buddy import Area, Buddy, Canvas, rgba

ROUND = 1  # NSLineCapStyleRound / NSLineJoinStyleRound
USES_LINE_FRAGMENT_ORIGIN = getattr(AppKit, "NSStringDrawingUsesLineFragmentOrigin", 1)
CENTER = getattr(AppKit, "NSTextAlignmentCenter", 2)
COMPOSITE_COPY = getattr(AppKit, "NSCompositingOperationCopy", 1)
BORDERLESS = getattr(AppKit, "NSWindowStyleMaskBorderless", 0)
FLOATING_LEVEL = getattr(AppKit, "NSFloatingWindowLevel", 3)
ACCESSORY_APP = getattr(AppKit, "NSApplicationActivationPolicyAccessory", 1)  # no Dock icon
ALL_SPACES = 1 | 16 | 64  # can join all spaces | stationary | ignores cycle


def _ns_color(color):
    return NSColor.colorWithSRGBRed_green_blue_alpha_(*rgba(color))


class MacCanvas(Canvas):
    """Drawing on an AppKit view whose coordinates start at the top-left."""

    @staticmethod
    def _path(shape):
        path = NSBezierPath.bezierPath()
        for cmd in shape.cmds:
            if cmd[0] == "M":
                path.moveToPoint_((cmd[1], cmd[2]))
            elif cmd[0] == "L":
                path.lineToPoint_((cmd[1], cmd[2]))
            elif cmd[0] == "C":
                path.curveToPoint_controlPoint1_controlPoint2_((cmd[5], cmd[6]), (cmd[1], cmd[2]), (cmd[3], cmd[4]))
            else:
                path.closePath()
        path.setLineCapStyle_(ROUND)
        path.setLineJoinStyle_(ROUND)
        return path

    @staticmethod
    def _transform():
        return NSAffineTransform.transform()

    def save(self):
        NSGraphicsContext.saveGraphicsState()

    def restore(self):
        NSGraphicsContext.restoreGraphicsState()

    def translate(self, dx, dy):
        t = self._transform()
        t.translateXBy_yBy_(dx, dy)
        t.concat()

    def rotate(self, degrees):
        t = self._transform()
        t.rotateByDegrees_(degrees)
        t.concat()

    def scale(self, factor):
        t = self._transform()
        t.scaleBy_(factor)
        t.concat()

    def scale_xy(self, sx, sy):
        t = self._transform()
        t.scaleXBy_yBy_(sx, sy)
        t.concat()

    def fill_stroke(self, shape, fill=None, outline=None, width=0):
        path = self._path(shape)
        if fill:
            _ns_color(fill).setFill()
            path.fill()
        if outline:
            _ns_color(outline).setStroke()
            path.setLineWidth_(width)
            path.stroke()

    def clip(self, shape):
        self._path(shape).addClip()

    def fill_rect(self, x, y, w, h, color):
        _ns_color(color).setFill()
        NSBezierPath.fillRect_(NSMakeRect(x, y, w, h))

    def _string(self, text, size, color, bold=False, centered=False):
        font = NSFont.boldSystemFontOfSize_(size) if bold else NSFont.systemFontOfSize_(size)
        attributes = {AppKit.NSFontAttributeName: font, AppKit.NSForegroundColorAttributeName: _ns_color(color)}
        if centered:
            paragraph = NSMutableParagraphStyle.alloc().init()
            paragraph.setAlignment_(CENTER)
            attributes[AppKit.NSParagraphStyleAttributeName] = paragraph
        return NSAttributedString.alloc().initWithString_attributes_(text, attributes)

    def text(self, x, y, text, size, color, bold=False):
        self._string(text, size, color, bold).drawAtPoint_((x, y))

    def measure(self, text, size, max_width):
        rect = self._string(text, size, "#000000", centered=True).boundingRectWithSize_options_(
            (max_width, 10000), USES_LINE_FRAGMENT_ORIGIN)
        return rect.size.width, rect.size.height

    def text_box(self, x, y, w, h, text, size, color):
        string = self._string(text, size, color, centered=True)
        _, text_h = self.measure(text, size, w)
        top = y + max(0, (h - text_h) / 2)  # center vertically
        string.drawWithRect_options_(NSMakeRect(x, top, w, h), USES_LINE_FRAGMENT_ORIGIN)


class BuddyView(NSView):
    host = None  # the MacHost (one buddy per app)

    def isFlipped(self):
        return True  # y grows downwards, like the drawing code expects

    def acceptsFirstMouse_(self, event):
        return True  # react to the first click even when another app is active

    def drawRect_(self, rect):
        NSColor.clearColor().set()
        AppKit.NSRectFillUsingOperation(self.bounds(), COMPOSITE_COPY)  # erase the last frame
        self.host.buddy.draw(MacCanvas())

    def mouseDown_(self, event):
        self.host.buddy.press(*self.host.mouse())

    def mouseDragged_(self, event):
        self.host.buddy.drag(*self.host.mouse())
        self.host.move_window()

    def mouseUp_(self, event):
        self.host.buddy.release()

    def rightMouseDown_(self, event):
        NSMenu.popUpContextMenu_withEvent_forView_(self.host.build_menu(), event, self)


class PropView(NSView):
    """Draws one toy (ball, butterfly) in its own little window."""

    host = None

    def isFlipped(self):
        return True

    def drawRect_(self, rect):
        NSColor.clearColor().set()
        AppKit.NSRectFillUsingOperation(self.bounds(), COMPOSITE_COPY)
        for prop, (window, view) in self.host.prop_windows.items():
            if view == self:
                prop.draw(MacCanvas())


class Driver(NSObject):
    """Receives the animation timer and menu clicks."""

    host = None

    def tick_(self, timer):
        self.host.tick()

    def menuClicked_(self, sender):
        self.host.menu_clicked(sender)


class MacHost:
    def __init__(self):
        self.app = NSApplication.sharedApplication()
        self.app.setActivationPolicy_(ACCESSORY_APP)
        self.screen_height = NSScreen.screens()[0].frame().size.height  # main display
        visible = NSScreen.mainScreen().visibleFrame()  # without the menu bar and Dock
        top = self.screen_height - (visible.origin.y + visible.size.height)
        self.area = Area(visible.origin.x, top, visible.origin.x + visible.size.width,
                         top + visible.size.height)
        self.buddy = None
        self.window = None
        self.view = None
        self._callbacks = []
        self.prop_windows = {}  # toy -> (window, view)

    def show(self, buddy: Buddy):
        self.buddy = buddy
        buddy.on_quit = self.quit
        rect = NSMakeRect(0, 0, buddy.W, buddy.H)
        window = self._floating_window(buddy.W, buddy.H)
        BuddyView.host = self
        self.view = BuddyView.alloc().initWithFrame_(rect)
        window.setContentView_(self.view)
        self.window = window
        self.move_window()
        window.orderFrontRegardless()

        Driver.host = self
        self.driver = Driver.alloc().init()
        self.timer = NSTimer.timerWithTimeInterval_target_selector_userInfo_repeats_(
            Buddy.FRAME, self.driver, "tick:", None, True)
        # common modes: keep animating while a menu is open or the buddy is being dragged
        NSRunLoop.currentRunLoop().addTimer_forMode_(self.timer, AppKit.NSRunLoopCommonModes)

    def mouse(self):
        """Mouse position in top-left-origin screen coordinates."""
        point = NSEvent.mouseLocation()
        return point.x, self.screen_height - point.y

    def move_window(self):
        b = self.buddy
        self.window.setFrameOrigin_((b.x, self.screen_height - b.y - b.H))

    def tick(self):
        self.buddy.tick()
        self.move_window()
        self.view.setNeedsDisplay_(True)
        self.sync_props()

    def _floating_window(self, width, height):
        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, width, height), BORDERLESS, NSBackingStoreBuffered, False)
        window.setOpaque_(False)
        window.setBackgroundColor_(NSColor.clearColor())
        window.setHasShadow_(False)
        window.setLevel_(FLOATING_LEVEL)
        window.setCollectionBehavior_(ALL_SPACES)
        return window

    def sync_props(self):
        """Open, move and close the little windows for the toys on screen."""
        for prop in list(self.prop_windows):
            if prop not in self.buddy.props:
                window, _ = self.prop_windows.pop(prop)
                window.orderOut_(None)
        for prop in self.buddy.props:
            if prop not in self.prop_windows:
                window = self._floating_window(prop.W, prop.H)
                window.setIgnoresMouseEvents_(True)  # clicks go straight through toys
                PropView.host = self
                view = PropView.alloc().initWithFrame_(NSMakeRect(0, 0, prop.W, prop.H))
                window.setContentView_(view)
                window.orderFrontRegardless()
                self.prop_windows[prop] = (window, view)
            window, view = self.prop_windows[prop]
            window.setFrameOrigin_((prop.x, self.screen_height - prop.y - prop.H))
            view.setNeedsDisplay_(True)

    def build_menu(self):
        menu = NSMenu.alloc().initWithTitle_(self.buddy.name)
        menu.setAutoenablesItems_(False)
        self._callbacks = []
        for item in self.buddy.menu_items():
            if item is None:
                menu.addItem_(NSMenuItem.separatorItem())
                continue
            label, checked, callback = item
            entry = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(label, "menuClicked:", "")
            entry.setTarget_(self.driver)
            entry.setTag_(len(self._callbacks))
            entry.setEnabled_(True)
            if checked is not None:
                entry.setState_(1 if checked else 0)
            self._callbacks.append((checked, callback))
            menu.addItem_(entry)
        return menu

    def menu_clicked(self, sender):
        checked, callback = self._callbacks[sender.tag()]
        callback(None if checked is None else not checked)

    def run(self):
        self.app.run()

    def quit(self):
        self.app.terminate_(None)

