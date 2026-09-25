"""Small vendored Lucide icon, rendered in the toolkit palette."""

# Source: https://github.com/lucide-icons/lucide/blob/main/icons/info.svg
# ISC License
# Copyright (c) 2026 Lucide Icons and Contributors
# Permission to use, copy, modify, and/or distribute this software for any
# purpose with or without fee is hereby granted, provided that the above
# copyright notice and this permission notice appear in all copies.
# THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
# WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN AN
# ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION, ARISING OUT OF
# OR IN CONNECTION WITH THE USE OR PERFORMANCE OF THIS SOFTWARE.
#
# This icon derives from Feather, under the MIT License:
# Copyright (c) 2013-present Cole Bemis
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from xml.etree import ElementTree

from PySide6.QtGui import QIcon, QPixmap

INFO_SVG = '''<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24"
 viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
 stroke-linecap="round" stroke-linejoin="round">
 <circle cx="12" cy="12" r="10" />
 <path d="M12 16v-4" /><path d="M12 8h.01" />
</svg>'''


def info_icon(color, hover_color):
    icon = QIcon()
    for mode, stroke in ((QIcon.Normal, color), (QIcon.Active, hover_color),
                         (QIcon.Disabled, color), (QIcon.Selected, hover_color)):
        svg = ElementTree.fromstring(INFO_SVG)
        svg.set("stroke", stroke)
        svg.set("width", "60")
        svg.set("height", "60")
        pixmap = QPixmap()
        if not pixmap.loadFromData(ElementTree.tostring(svg), "SVG"):
            raise RuntimeError("Could not render the toolkit info icon.")
        pixmap.setDevicePixelRatio(3)
        icon.addPixmap(pixmap, mode)
    return icon
