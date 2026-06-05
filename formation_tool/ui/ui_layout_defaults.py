"""Shared window sizes for the formation tool UI."""

from dataclasses import dataclass


@dataclass(frozen=True)
class WindowLayout:
    geometry: str
    minsize: tuple[int, int]


MAIN_WINDOW = WindowLayout("1280x860", (1100, 740))
GROUP_WEIGHT_DIALOG = WindowLayout("1180x820", (980, 680))
REBATE_RULES_DIALOG = WindowLayout("1380x820", (1160, 660))
SINGLE_SAMPLING_DIALOG = WindowLayout("620x460", (520, 360))


def apply_window_layout(window, layout: WindowLayout):
    window.geometry(layout.geometry)
    window.minsize(*layout.minsize)


MAIN_WINDOW_GEOMETRY = MAIN_WINDOW.geometry
MAIN_WINDOW_MINSIZE = MAIN_WINDOW.minsize
GROUP_WEIGHT_DIALOG_GEOMETRY = GROUP_WEIGHT_DIALOG.geometry
GROUP_WEIGHT_DIALOG_MINSIZE = GROUP_WEIGHT_DIALOG.minsize
REBATE_RULES_DIALOG_GEOMETRY = REBATE_RULES_DIALOG.geometry
REBATE_RULES_DIALOG_MINSIZE = REBATE_RULES_DIALOG.minsize
SINGLE_SAMPLING_DIALOG_GEOMETRY = SINGLE_SAMPLING_DIALOG.geometry
SINGLE_SAMPLING_DIALOG_MINSIZE = SINGLE_SAMPLING_DIALOG.minsize
