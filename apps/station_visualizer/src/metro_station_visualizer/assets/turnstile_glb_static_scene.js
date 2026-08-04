import * as THREE from "three";

export function setupTurnstileLighting(scene, camera) {
  scene.background = new THREE.Color(0xeef2f4);
  camera.position.set(0, 30, 18);
  camera.lookAt(0, 0, 0);
  scene.add(new THREE.HemisphereLight(0xffffff, 0xcfd8dc, 1.8));
  const key = new THREE.DirectionalLight(0xffffff, 2.6);
  key.position.set(-7, 14, 9);
  scene.add(key);
}

export function rebuildStaticTurnstileScene(scene, run) {
  for (const object of [...scene.children]) {
    if (object.userData.staticScene) scene.remove(object);
  }
  if (!run) return;

  const group = new THREE.Group();
  group.userData.staticScene = true;
  addFloor(group, run);
  addPath(group, run);
  addQueueSlots(group, run);
  addGate(group, run);
  scene.add(group);
}

export function worldToScene(run, point) {
  return {
    x: Number(point[0]) - Number(run.scenario.world_width) / 2,
    z: Number(point[1]) - Number(run.scenario.world_height) / 2,
  };
}

function addFloor(group, run) {
  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(run.scenario.world_width + 2, run.scenario.world_height + 2),
    new THREE.MeshStandardMaterial({ color: 0xf7f8f8, roughness: 0.8 }),
  );
  floor.rotation.x = -Math.PI / 2;
  group.add(floor);
  addZone(group, run, run.scenario.source_position, 0x2f6f9f, 0.8);
  addZone(group, run, run.scenario.exit_position, 0x2f8f5b, 0.9);
}

function addPath(group, run) {
  const points = [
    run.scenario.source_position,
    ...run.scenario.pre_gate_targets,
    run.scenario.queue_anchor,
    run.scenario.exit_position,
  ];
  const geometry = new THREE.BufferGeometry().setFromPoints(
    points.map((point) => vector(run, point, 0.035)),
  );
  group.add(new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: 0x86939d })));
}

function addQueueSlots(group, run) {
  for (const slot of (run.scenario.queue_slots || []).slice(0, 30)) {
    const marker = new THREE.Mesh(
      new THREE.RingGeometry(0.16, 0.2, 20),
      new THREE.MeshBasicMaterial({ color: 0xbf8f00, side: THREE.DoubleSide }),
    );
    const point = worldToScene(run, slot);
    marker.position.set(point.x, 0.045, point.z);
    marker.rotation.x = -Math.PI / 2;
    group.add(marker);
  }
}

function addGate(group, run) {
  const point = worldToScene(run, run.scenario.gate_position);
  for (const offset of [-0.24, 0.24]) {
    const post = new THREE.Mesh(
      new THREE.BoxGeometry(0.12, 0.46, 0.92),
      new THREE.MeshStandardMaterial({ color: 0x263238, roughness: 0.6 }),
    );
    post.position.set(point.x, 0.23, point.z + offset);
    group.add(post);
  }
}

function addZone(group, run, position, color, radius) {
  const zone = new THREE.Mesh(
    new THREE.CircleGeometry(radius, 48),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.14, side: THREE.DoubleSide }),
  );
  const point = worldToScene(run, position);
  zone.position.set(point.x, 0.025, point.z);
  zone.rotation.x = -Math.PI / 2;
  group.add(zone);
}

function vector(run, point, y = 0) {
  const mapped = worldToScene(run, point);
  return new THREE.Vector3(mapped.x, y, mapped.z);
}
