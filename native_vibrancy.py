"""native_vibrancy.py — Real macOS glassmorphism via NSVisualEffectView.

Injects NSVisualEffectView behind a PyQt6 window using pyobjc.
All imports happen lazily inside apply_vibrancy() to avoid conflicts
with PyQt6's NSApplication initialization.

Usage:
    from native_vibrancy import apply_vibrancy
    # Call after window.show() via QTimer.singleShot(80, ...)
    apply_vibrancy(window, corner_radius=22.0, material="hud")
"""
from __future__ import annotations

import logging
import sys

# Constants (from AppKit headers — no imports needed at module level)
_MATERIAL_HUD = 13         # NSVisualEffectMaterialHUDWindow — dark glass
_MATERIAL_DARK = 2         # NSVisualEffectMaterialDark
_MATERIAL_ULTRA_DARK = 9   # NSVisualEffectMaterialUltraDark
_MATERIAL_POPOVER = 6      # NSVisualEffectMaterialPopover — lighter
_BLENDING_BEHIND = 0       # NSVisualEffectBlendingModeBehindWindow
_STATE_ACTIVE = 1          # NSVisualEffectStateActive
_FLEXIBLE_ALL = 18         # NSAutoresizingMask: flexible width (2) + height (16)
_WINDOW_BELOW = -1         # NSWindowOrderingMode: NSWindowBelow (below all siblings)

MATERIAL_MAP = {
    "hud": _MATERIAL_HUD,
    "dark": _MATERIAL_DARK,
    "ultra_dark": _MATERIAL_ULTRA_DARK,
    "popover": _MATERIAL_POPOVER,
}


def apply_vibrancy(
    qt_widget,
    corner_radius: float = 22.0,
    material: str = "hud",
) -> bool:
    """Inject NSVisualEffectView behind qt_widget's native NSView.

    All AppKit/objc imports happen here (lazy) to avoid conflicting with
    PyQt6's NSApplication at module import time.

    Args:
        qt_widget: A visible top-level QWidget.
        corner_radius: Corner radius in points (match your Qt border-radius).
        material: One of 'hud', 'dark', 'ultra_dark', 'popover'.

    Returns:
        True if vibrancy was applied, False if skipped or failed.
    """
    if sys.platform != "darwin":
        return False

    try:
        import objc
        from AppKit import NSColor, NSVisualEffectView
        from ctypes import c_void_p
    except ImportError:
        logging.debug("native_vibrancy: pyobjc-framework-Cocoa not available")
        return False

    try:
        ptr = int(qt_widget.winId())
        ns_view = objc.objc_object(c_void_p=ptr)
        ns_window = ns_view.window()

        if ns_window is None:
            logging.warning("native_vibrancy: NSWindow is None — window not yet shown?")
            return False

        # 1. Make NSWindow background clear
        ns_window.setBackgroundColor_(NSColor.clearColor())
        ns_window.setOpaque_(False)

        # 2. Make the Qt content view layer-backed + transparent
        ns_view.setWantsLayer_(True)
        ns_view.layer().setCornerRadius_(corner_radius)
        ns_view.layer().setMasksToBounds_(True)

        # 3. Get the superview (NSThemeFrame) — this is the actual
        #    container where we can place siblings below the Qt view.
        #    Qt paints ALL widgets into ns_view's single layer, so any
        #    NSView added as a CHILD of ns_view is always drawn on top.
        #    We must insert at the superview level, below ns_view.
        theme_frame = ns_view.superview()
        if theme_frame is None:
            logging.warning("native_vibrancy: no superview (NSThemeFrame) found")
            return False

        # 4. Create the vibrancy effect view (in superview coordinates)
        frame = ns_view.frame()
        effect_view = NSVisualEffectView.alloc().initWithFrame_(frame)
        effect_view.setMaterial_(MATERIAL_MAP.get(material, _MATERIAL_HUD))
        effect_view.setBlendingMode_(_BLENDING_BEHIND)
        effect_view.setState_(_STATE_ACTIVE)
        effect_view.setAutoresizingMask_(_FLEXIBLE_ALL)
        effect_view.setWantsLayer_(True)
        effect_view.layer().setCornerRadius_(corner_radius)
        effect_view.layer().setMasksToBounds_(True)

        # 5. Insert into the NSThemeFrame, BELOW the Qt content view.
        theme_frame.addSubview_positioned_relativeTo_(
            effect_view, _WINDOW_BELOW, ns_view
        )

        logging.info(
            "native_vibrancy: applied material=%s radius=%.0f", material, corner_radius
        )
        return True

    except Exception as exc:
        logging.warning("native_vibrancy: %s: %s", type(exc).__name__, exc)
        return False
