import { applyAtlasFrame, loadSpriteAtlas } from "./passenger_sprite_atlas.js?v=ops-config-1";

export const ASSET_PREVIEW_DEFS = [
  { id: "entry", label: "进站", color: "#16695a", typeId: "commuter_blue_backpack" },
  { id: "exit", label: "出站", color: "#2a5f91", typeId: "business_briefcase" },
  { id: "luggage", label: "行李", color: "#a96300", typeId: "yellow_coat_tote" },
  { id: "slow", label: "慢行", color: "#6f5a8d", typeId: "elder_cane" },
];

export function mountPassengerAssetScene(THREE, host) {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(33, 1, 0.1, 100);
  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, preserveDrawingBuffer: true });
  const models = [];
  let disposed = false;

  camera.position.set(0, 2.3, 6.3);
  camera.lookAt(0, 0.72, 0);
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  host.appendChild(renderer.domElement);
  scene.add(new THREE.HemisphereLight(0xffffff, 0xc9beb0, 1.65), createStageBase(THREE));

  loadSpriteAtlas(THREE)
    .then((atlas) => {
      if (disposed) return;
      ASSET_PREVIEW_DEFS.forEach((asset, index) => {
        const model = createSpritePassenger(THREE, atlas, asset, index);
        model.position.x = (index - 1.5) * 1.08;
        scene.add(model);
        models.push(model);
      });
      dispatchSceneStatus(host, "ready");
    })
    .catch(() => dispatchSceneStatus(host, "failed"));

  const resize = () => resizeRenderer(host, renderer, camera);
  const observer = new ResizeObserver(resize);
  observer.observe(host);
  resize();

  let frameId = 0;
  const animate = (timeMs) => {
    animateSpritePassengers(models, host, timeMs / 1000);
    renderer.render(scene, camera);
    frameId = window.requestAnimationFrame(animate);
  };
  frameId = window.requestAnimationFrame(animate);

  return () => {
    disposed = true;
    window.cancelAnimationFrame(frameId);
    observer.disconnect();
    disposeScene(scene);
    renderer.dispose();
    renderer.domElement.remove();
  };
}

function dispatchSceneStatus(host, status) {
  host.dispatchEvent(new CustomEvent("passenger-asset-scene-status", { detail: { status } }));
}

function resizeRenderer(host, renderer, camera) {
  const rect = host.getBoundingClientRect();
  const width = Math.max(240, Math.floor(rect.width));
  const height = Math.max(150, Math.floor(rect.height || 168));
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}

function createStageBase(THREE) {
  const group = new THREE.Group();
  const base = new THREE.Mesh(
    new THREE.CylinderGeometry(2.95, 3.16, 0.06, 48),
    new THREE.MeshStandardMaterial({ color: 0xfffcf7, roughness: 0.78 }),
  );
  base.position.y = -0.04;
  group.add(base);

  const ring = new THREE.Mesh(
    new THREE.TorusGeometry(2.72, 0.012, 8, 64),
    new THREE.MeshStandardMaterial({ color: 0xd9d1c4, roughness: 0.8 }),
  );
  ring.rotation.x = Math.PI / 2;
  ring.position.y = 0.01;
  group.add(ring);
  return group;
}

function createSpritePassenger(THREE, atlas, asset, index) {
  const group = new THREE.Group();
  const map = atlas.texture.clone();
  const material = new THREE.MeshBasicMaterial({
    map,
    transparent: true,
    side: THREE.DoubleSide,
    alphaTest: 0.08,
  });
  const plane = new THREE.Mesh(new THREE.PlaneGeometry(0.92, 0.92), material);
  plane.position.y = 0.64;
  group.add(plane, createSpriteShadow(THREE));
  group.userData = {
    assetId: asset.id,
    baseX: (index - 1.5) * 1.08,
    frameKey: "",
    index,
    sprite: { atlas, map, typeId: asset.typeId },
  };
  updateSpriteFrame(group, "walk", "down", 0);
  return group;
}

function createSpriteShadow(THREE) {
  const shadow = new THREE.Mesh(
    new THREE.CircleGeometry(0.28, 24),
    new THREE.MeshBasicMaterial({ color: 0x000000, transparent: true, opacity: 0.12, depthWrite: false }),
  );
  shadow.rotation.x = -Math.PI / 2;
  shadow.position.y = 0.015;
  return shadow;
}

function animateSpritePassengers(models, host, time) {
  const entryShare = Number(host.dataset.entryShare || 0);
  const exitShare = Number(host.dataset.exitShare || 0);
  for (const model of models) {
    const share = modelShare(model.userData.assetId, entryShare, exitShare);
    const orbit = time * 0.5 + model.userData.index * (Math.PI / 2);
    const frame = Math.floor((time * 5.2 + model.userData.index * 0.6) % frameCount(model));
    const action = model.userData.assetId === "slow" ? "queue" : "walk";
    model.position.x = model.userData.baseX + Math.sin(orbit) * 0.16;
    model.position.y = Math.sin(time * 2.1 + model.userData.index) * 0.035;
    model.position.z = Math.cos(orbit) * 0.34;
    model.rotation.y = Math.sin(orbit) * 0.22;
    model.scale.setScalar((1.0 + share * 0.16) * (1 + model.position.z * 0.06));
    updateSpriteFrame(model, action, directionForRotation(orbit), frame);
  }
}

function frameCount(model) {
  return Math.max(1, Number(model.userData.sprite.atlas.meta?.frame_count) || 4);
}

function directionForRotation(rotationY) {
  const turn = ((rotationY % (Math.PI * 2)) + Math.PI * 2) % (Math.PI * 2);
  if (turn < Math.PI * 0.25 || turn >= Math.PI * 1.75) return "down";
  if (turn < Math.PI * 0.75) return "right";
  if (turn < Math.PI * 1.25) return "up";
  return "left";
}

function updateSpriteFrame(model, action, direction, frameIndex) {
  const sprite = model.userData.sprite;
  const key = `${sprite.typeId}/${action}/${direction}/${frameIndex}`;
  if (key === model.userData.frameKey) return;
  const frame = sprite.atlas.meta.frames?.[key];
  if (!frame) return;
  applyAtlasFrame(sprite.map, frame, sprite.atlas.texture.image);
  model.userData.frameKey = key;
}

function modelShare(assetId, entryShare, exitShare) {
  if (assetId === "entry") return entryShare;
  if (assetId === "exit") return exitShare;
  return 0.18;
}

function disposeScene(scene) {
  scene.traverse((object) => {
    object.geometry?.dispose?.();
    if (Array.isArray(object.material)) {
      object.material.forEach(disposeMaterial);
      return;
    }
    disposeMaterial(object.material);
  });
}

function disposeMaterial(material) {
  material?.map?.dispose?.();
  material?.dispose?.();
}
