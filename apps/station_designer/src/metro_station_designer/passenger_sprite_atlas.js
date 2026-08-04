const ATLAS_IMAGE_URL = "/visual-assets/passenger_sprite_atlas.png";
const ATLAS_META_URL = "/visual-assets/passenger_sprite_atlas.json";

export function loadSpriteAtlas(THREE) {
  return Promise.all([loadTexture(THREE, ATLAS_IMAGE_URL), loadJson(ATLAS_META_URL)]).then(
    ([texture, meta]) => ({ texture, meta }),
  );
}

export function applyAtlasFrame(map, frame, image) {
  map.repeat.set(frame.w / image.width, frame.h / image.height);
  map.offset.set(frame.x / image.width, 1 - (frame.y + frame.h) / image.height);
  map.needsUpdate = true;
}

function loadTexture(THREE, url) {
  return new Promise((resolve, reject) => {
    new THREE.TextureLoader().load(
      url,
      (texture) => {
        texture.colorSpace = THREE.SRGBColorSpace;
        texture.magFilter = THREE.NearestFilter;
        texture.minFilter = THREE.NearestFilter;
        resolve(texture);
      },
      undefined,
      reject,
    );
  });
}

function loadJson(url) {
  return fetch(url).then((response) => {
    if (!response.ok) throw new Error(`Could not load passenger sprite atlas metadata: ${url}`);
    return response.json();
  });
}
