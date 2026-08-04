using System;
using System.Collections.Generic;
using UnityEngine;

namespace MetroReplay.Presentation
{
    public sealed class PassengerBaseShowcase : IDisposable
    {
        private readonly List<Material> _materials = new List<Material>();
        private GameObject _root;

        public void Build(IReadOnlyList<GameObject> prototypes, Transform stationRoot, Camera camera)
        {
            if (prototypes == null || prototypes.Count == 0)
                throw new ArgumentException("Passenger prototypes are required.", nameof(prototypes));
            if (camera == null)
                throw new ArgumentNullException(nameof(camera));
            stationRoot?.gameObject.SetActive(false);
            _root = new GameObject("PassengerBaseShowcase");
            AddBackdrop();
            AddStudioLights();
            var block = new MaterialPropertyBlock();
            for (var index = 0; index < prototypes.Count; index++)
                AddAvatar(prototypes[index], index, block);
            ConfigureCamera(camera);
        }

        public void Dispose()
        {
            if (_root != null)
                UnityEngine.Object.Destroy(_root);
            foreach (var material in _materials)
                if (material != null)
                    UnityEngine.Object.Destroy(material);
            _materials.Clear();
        }

        private void AddAvatar(GameObject prototype, int index, MaterialPropertyBlock block)
        {
            var avatar = UnityEngine.Object.Instantiate(prototype, _root.transform, false);
            avatar.name = $"RealisticBase_{index + 1:00}";
            avatar.transform.SetPositionAndRotation(
                new Vector3((index - 3.5f) * 1.25f, 0f, 0f),
                Quaternion.Euler(0f, 180f, 0f));
            avatar.SetActive(true);
            PassengerAppearanceApplicator.Apply(
                avatar.GetComponentsInChildren<Renderer>(true), index * 13 + 7, block);
            var animator = avatar.GetComponentInChildren<Animator>(true);
            var current = string.Empty;
            PassengerAnimationPlayer.Play(animator, null, ref current,
                index % 3 == 0 ? "Idle_Loop" : "Walk_Loop", index);
        }

        private static void ConfigureCamera(Camera camera)
        {
            var controller = camera.GetComponent<OrbitCameraController>();
            if (controller != null)
                controller.enabled = false;
            camera.transform.position = new Vector3(0f, 1.62f, -8.8f);
            camera.transform.LookAt(new Vector3(0f, 0.92f, 0f));
        }

        private void AddBackdrop()
        {
            AddBox("ShowcaseFloor", new Vector3(0f, -0.08f, 0.6f),
                new Vector3(11.2f, 0.12f, 4.8f), new Color(0.13f, 0.15f, 0.18f));
            AddBox("ShowcaseBackWall", new Vector3(0f, 1.8f, 2.0f),
                new Vector3(11.2f, 3.8f, 0.10f), new Color(0.06f, 0.08f, 0.11f));
        }

        private void AddStudioLights()
        {
            AddPointLight("ShowcaseKey", new Vector3(-4.2f, 3.8f, -2.2f), 22000f, new Color(1f, 0.86f, 0.72f));
            AddPointLight("ShowcaseFill", new Vector3(4.2f, 3.2f, -1.2f), 18000f, new Color(0.70f, 0.84f, 1f));
            AddPointLight("ShowcaseRim", new Vector3(0f, 3.6f, 2.2f), 16000f, new Color(0.78f, 0.88f, 1f));
        }

        private void AddPointLight(string name, Vector3 position, float intensity, Color color)
        {
            var lightObject = new GameObject(name);
            lightObject.transform.SetParent(_root.transform, false);
            lightObject.transform.position = position;
            var light = lightObject.AddComponent<Light>();
            light.type = LightType.Point;
            light.intensity = intensity;
            light.range = 14f;
            light.color = color;
            light.shadows = LightShadows.Soft;
            HdrpStationLook.EnsureAdditionalLightData(light);
        }

        private void AddBox(string name, Vector3 position, Vector3 scale, Color color)
        {
            var box = GameObject.CreatePrimitive(PrimitiveType.Cube);
            box.name = name;
            box.transform.SetParent(_root.transform, false);
            box.transform.position = position;
            box.transform.localScale = scale;
            var collider = box.GetComponent<Collider>();
            if (collider != null)
                UnityEngine.Object.Destroy(collider);
            var material = ReplayMaterialFactory.Create(name + "Material", color);
            _materials.Add(material);
            box.GetComponent<Renderer>().sharedMaterial = material;
        }
    }
}
