# Texture credits

Surface maps used by the 3D scene. All are derived from public NASA/USGS mission data. They are
vendored here rather than hotlinked so the scene never depends on a third-party host at runtime
and never renders as untextured spheres.

| File | Source | Underlying data |
|---|---|---|
| `mars_color.jpg`, `mars_bump.jpg` | James Hastings-Trew, Planet Pixel Emporium, via the `threex.planets` repository | Viking colour mosaic and MOLA elevation |
| `moon_color.jpg`, `moon_bump.jpg` | same | Clementine mosaic and lunar topography |
| `sun_color.jpg` | same | solar photosphere imagery |
| `jupiter_color.jpg`, `saturn_color.jpg`, `saturn_ring.jpg`, `venus_color.jpg`, `mercury_color.jpg` | same | Voyager, Cassini, Magellan and MESSENGER imagery |
| `earth_color.jpg`, `earth_normal.jpg`, `earth_specular.jpg`, `earth_clouds.png` | three.js examples (`examples/textures/planets`), MIT-licensed repository | NASA Blue Marble |

The Planet Pixel Emporium maps are published for free use with credit appreciated. Credit is
given here and in the interface footer text.

Titan ships no map in this set and is a featureless orange haze from orbit in any case, so it
is rendered as flat colour plus an atmosphere shell rather than with an invented surface.

Relative body sizes in the scene are true (Earth is 1.9x Mars, the Moon 0.27x Earth). Distances
are not, and cannot be: Mars at true separation from Earth would be a single pixel.
