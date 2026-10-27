"""Conservative SVG subset for generated image assets; no active content or URLs."""
import re
from defusedxml import ElementTree as SafeET
from xml.etree import ElementTree as ET

TAGS = {'svg','g','path','rect','circle','ellipse','line','polyline','polygon','text','tspan','defs','linearGradient','radialGradient','stop','clipPath','mask','title','desc','use','symbol'}
ATTRS = {'id','x','y','x1','y1','x2','y2','cx','cy','r','rx','ry','width','height','d','points','viewBox','fill','fill-opacity','fill-rule','stroke','stroke-width','stroke-linecap','stroke-linejoin','stroke-dasharray','stroke-opacity','opacity','transform','font-size','font-family','font-weight','text-anchor','dominant-baseline','offset','stop-color','stop-opacity','gradientUnits','gradientTransform','clip-path','mask','preserveAspectRatio','dx','dy','href'}


def sanitize_svg(value: str) -> str:
    root = SafeET.fromstring(value, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    if root.tag.split('}')[-1] != 'svg':
        raise ValueError('Expected an SVG image')
    for parent in root.iter():
        for child in list(parent):
            if child.tag.split('}')[-1] not in TAGS:
                parent.remove(child)
        for name, content in list(parent.attrib.items()):
            local = name.split('}')[-1]
            if local not in ATTRS or local.lower().startswith('on'):
                del parent.attrib[name]
            elif local == 'href' and not content.startswith('#'):
                del parent.attrib[name]
            elif 'url(' in content.lower() and not re.fullmatch(r'url\(#[A-Za-z_][\w:.-]*\)', content.strip()):
                del parent.attrib[name]
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    if not root.tag.startswith('{'):
        root.set('xmlns', 'http://www.w3.org/2000/svg')
    return ET.tostring(root, encoding='unicode')
