# FRAME film material interface

The scanner workspace now uses a 35 mm film-lab visual language: perforated film
edges, frame numbers, contact-sheet cards, an image gate, editorial headings and
quiet material transitions. Home, Scan, Rolls, Settings and phone navigation share
the same palette and components. The selected family also carries into Develop.

## Film families

B&W backing reference: Simon King's [photograph of developed Fomapan 200 and
Kentmere PAN 200 strips](https://www.35mmc.com/17/09/2025/battle-of-the-budgets-continued-fomapan-200-kentmere-200-35mm/)
identifies Kentmere as the lower strip, also visibly edge-labelled KENTMERE PAN 200.
The unexposed top rebate at image coordinates x=370–840, y=375–380 in the 1024×683
JPEG has median RGB **172/161/176**, **#ACA1B0**: a muted lavender-grey. That
photographic sample now supplies the film-base colour across Home, the image
backing, thumbnails/gallery and fullscreen. It replaces the near-black backing
and subsequent unreferenced neutral-grey approximation.

This is sampled appearance under that photograph's illumination/white balance,
not a calibrated intrinsic colour or a scanner film-base measurement. HARMAN's
[product page](https://www.ilfordphoto.com/kentmere-200-35mm) describes PAN 200's
clear low-density base; its [technical sheet](https://www.ilfordphoto.com/wp/wp-content/uploads/2025/05/KENTMERE-PAN-200-260325.pdf)
identifies acetate. The UI colour is specifically based on the photographed
processed strip, not inferred solely from those words. Private reference bytes,
source URL/hash and sampled regions are retained under `.local/film-base-reference/`;
the photograph is not bundled into the application or committed.

Perforations use the surrounding dark-table colour to read as holes, with dark
edge lettering kept legible on the lighter rebate. Saved photo pixels and the
image-conversion film-base coefficients are unaffected.

| Selection | Workspace | New capture edit |
| --- | --- | --- |
| Color negative | Warm dark surfaces, amber edge markings, perforated film stock | Existing negative inversion and colour workflow |
| Black & white | Graphite, silver accents and monochrome film-stock details | Negative conversion with saturation -100; full tonal range retained |
| Slide | Cool light-table surfaces, pale slide mounts and blue accents | Positive-film polarity; no automatic negative inversion |

The always-visible radio selector changes the theme immediately and saves the
selection locally and through the authenticated API. If saving fails, the interface
returns to the previous selection. Scanner operations disable film changes. The
API stores stable film IDs and stamps the selected type onto new captures/sessions.

Choosing a film type does not start the scanner, change existing recipes, recolour
saved photographs, or enable unverified hardware. The B&W setting uses RGB
acquisition with a reversible desaturation edit; it does not request the scanner's
binary/threshold mode. Reset on a B&W capture retains its grayscale starting point.
Positive-film acquisition still needs its existing per-configuration hardware
validation; the new appearance is not a claim of slide-scanning readiness.

Film-specific decorative mounts are shadows, not changes to image dimensions.
Source views, border overlays and export geometry remain independent of the skin.
No film-grain filter, tint or decorative border is burned into acquired images.
Small transitions honor reduced-motion preferences. Keyboard focus and semantic
radio labels remain available on desktop and phone.

The viewer background is unadorned. Film backing and horizontal perforations hug
the actual image; Slide mode keeps the image mount and small mounted thumbnails.
Zoom, compare, borders, transport, rotation, mirror and favorite actions share a
floating icon dock with accessible labels and hover titles. Decorative viewer
lettering, repeated comparison captions and sidebar slogans have been removed.
An initial left/right perforation treatment was corrected following user review,
then moved off the viewer container entirely.

The dock also includes Previous frame. Short explanations appear on hover or
keyboard focus, including disabled-control reasons. Backward transport retains
the existing confirmation and capability checks; either direction requests a
quick preview afterward when that capability is available.

Fit to window uses the measured viewer area, visible crop, rotation and film
backing. Small previews enlarge to fit and fitted images follow window resizing.
Zoom percentages describe image scale: 100% maps an image pixel to a CSS screen
pixel, using recorded acquisition dimensions when available. Clicking the
percentage returns to that scale; it is separate from Fit. No image geometry or
export recipe is changed by zooming.

The miniature scan indicator draws its outline on arrival. Its fill/beam and the
live image beam follow received rows, never elapsed-time scan simulation. A gentle
waiting pulse, transport cue, thumbnail entrance, favorite acknowledgement and
small button/tooltip transitions provide the other motion. Reduced-motion mode
stops decorative animation and interpolation while keeping actual progress visible.

## Implementation and reference review

- `film-theme.tsx`: shared material metadata, film glyphs, accessible selector and
  preference helpers.
- `film-lab.css`: scanner/gallery/home materials and responsive layouts.
- `film-develop.css`: developing companion palette; timer logic is unchanged.
- `/api/cyberview/film-type`: authenticated preference update with active-operation
  protection; defaults for new captures use existing reversible edit parameters.

The supplied references were reviewed for hierarchy, component craft and restrained
interaction: [21st](https://21st.dev/), [React Bits](https://reactbits.dev/),
[Magic UI](https://magicui.design/), [Uiverse](https://uiverse.io/),
[Mobbin](https://mobbin.com/) and [Aceternity](https://ui.aceternity.com/).
motionvideo.xyz and its supplied short URL were inaccessible to the browsing tool.
This implementation uses original local CSS/SVG and the existing React stack,
without copied paid assets, new runtime packages or remote font/image dependencies.

## Review evidence

Home now uses the full available window width, including wide monitors. Its
featured image opening has the 36 × 24 mm frame's **3:2 proportions**, replacing
the original square treatment. Images are contained without stretching/cropping
their saved edits. Portrait or nonstandard images retain their whole content.

The fullscreen icon beside Shuffle opens an immersive photo view. It requests
native fullscreen when supported and uses a viewport overlay as a fallback.
The fullscreen image follows its saved aspect ratio. Escape/Close restores the
previous view; keyboard focus stays in the viewer while it is open. Open in
scanner returns to the selected frame. The desktop shell permits only ordinary
fullscreen for its own top-level local page; automatic fullscreen, remote pages,
subframes and other device/media permissions remain denied.

The static sample suite captures Home and Scan in all three materials, checks
phone overflow and theme persistence, verifies unchanged image URLs, and checks
reduced motion. Screenshots are under ignored `.local/frame-ui/`, including
`home-color_negative.png`, `home-bw_negative.png`, `home-positive.png` and the
corresponding scan/phone images. These are labeled sample photographs.

Live-API browser coverage uses an isolated temporary library and synthetic pipe
helper; it checks preference persistence, saved-edit preservation, navigation
into Develop and return. API tests verify that selection does not open the bridge,
B&W TIFFs retain many grey tones, slide selection does not promote unverified
hardware, and active capture blocks a type change.

No physical scanner operation or user-library migration was performed for this UI
redesign. Current commands/results are recorded at the top of `progress.md`.
