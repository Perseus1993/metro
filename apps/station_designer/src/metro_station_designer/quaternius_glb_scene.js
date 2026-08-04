const QUATERNIUS_GLB_URL = "assets/quaternius/AnimationLibrary_Godot_Standard.glb";

export function mountQuaterniusGlbScene(THREE, GLTFLoader, host) {
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, 1, 0.1, 100);
  const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true, preserveDrawingBuffer: true });
  const clock = new THREE.Clock();
  let mixer = null;
  let root = null;
  let disposed = false;

  camera.position.set(0, 1.45, 4.1);
  camera.lookAt(0, 0.86, 0);
  renderer.setClearColor(0x000000, 0);
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  host.appendChild(renderer.domElement);
  scene.add(new THREE.HemisphereLight(0xffffff, 0xd9d1c4, 1.6), createKeyLight(THREE), createFloor(THREE));

  new GLTFLoader().load(
    QUATERNIUS_GLB_URL,
    (gltf) => {
      if (disposed) return;
      root = gltf.scene;
      scene.add(root);
      normalizeModel(THREE, root);
      mixer = new THREE.AnimationMixer(root);
      playClip(mixer, gltf.animations);
      dispatchSceneStatus(host, "ready");
    },
    undefined,
    () => dispatchSceneStatus(host, "failed"),
  );

  const resize = () => resizeRenderer(host, renderer, camera);
  const observer = new ResizeObserver(resize);
  observer.observe(host);
  resize();

  let frameId = 0;
  const animate = () => {
    const delta = clock.getDelta();
    mixer?.update(delta);
    if (root) root.rotation.y += delta * 0.36;
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
  host.dispatchEvent(new CustomEvent("quaternius-glb-scene-status", { detail: { status } }));
}

function createKeyLight(THREE) {
  const light = new THREE.DirectionalLight(0xffffff, 2.5);
  light.position.set(3.1, 4.4, 3.2);
  return light;
}

function createFloor(THREE) {
  const floor = new THREE.Mesh(
    new THREE.CylinderGeometry(1.35, 1.48, 0.04, 48),
    new THREE.MeshStandardMaterial({ color: 0xfffcf7, roughness: 0.75 }),
  );
  floor.position.y = -0.02;
  return floor;
}

function resizeRenderer(host, renderer, camera) {
  const rect = host.getBoundingClientRect();
  const width = Math.max(240, Math.floor(rect.width));
  const height = Math.max(160, Math.floor(rect.height || 190));
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}

function normalizeModel(THREE, root) {
  const box = new THREE.Box3().setFromObject(root);
  const size = box.getSize(new THREE.Vector3());
  const center = box.getCenter(new THREE.Vector3());
  const scale = 1.56 / Math.max(size.y, 0.001);
  root.scale.setScalar(scale);
  root.position.set(-center.x * scale, -box.min.y * scale, -center.z * scale);
}

function playClip(mixer, animations) {
  const clip = animations.find((item) => item.name === "Jog_Fwd_Loop") || animations.find((item) => item.name === "Idle_Loop") || animations[0];
  if (!clip) return;
  const action = mixer.clipAction(clip);
  action.reset();
  action.play();
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
