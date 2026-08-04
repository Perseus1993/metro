using System;
using System.Collections.Generic;
using UnityEngine;

namespace MetroReplay.Presentation
{
    public sealed class PassengerSkinShowcase : IDisposable
    {
        private readonly List<Material> _materials = new List<Material>();
        private GameObject _root;

        public void Build(
            GameObject prototype,
            PassengerSkinAtlas skinAtlas,
            Transform stationRoot,
            Camera camera)
        {
            if (prototype == null)
                throw new ArgumentNullException(nameof(prototype));
            if (skinAtlas == null)
                throw new ArgumentNullException(nameof(skinAtlas));
            if (camera == null)
                throw new ArgumentNullException(nameof(camera));

            stationRoot?.gameObject.SetActive(false);
            _root = new GameObject("PassengerSkinShowcase");
            AddBackdrop();

            var propertyBlock = new MaterialPropertyBlock();
            for (var index = 0; index < PassengerSkinAtlas.VariantCount; index++)
            {
                var avatar = UnityEngine.Object.Instantiate(prototype, _root.transform, false);
                avatar.name = $"SkinVariant_{index + 1}";
                avatar.transform.SetPositionAndRotation(
                    new Vector3((index - 1.5f) * 1.65f, 0.84f, 0f),
                    Quaternion.Euler(0f, 180f, 0f));
                avatar.SetActive(true);
                skinAtlas.Apply(avatar.GetComponentsInChildren<Renderer>(true), index, propertyBlock);
                var animation = avatar.GetComponentInChildren<Animation>(true);
                var clipName = animation != null && animation.GetClip("Walk_Loop") != null
                    ? "Walk_Loop"
                    : "Idle_Loop";
                if (animation != null && animation.GetClip(clipName) != null)
                {
                    animation[clipName].normalizedTime = index * 0.19f;
                    animation.Play(clipName);
                }
            }

            var controller = camera.GetComponent<OrbitCameraController>();
            if (controller != null)
                controller.enabled = false;
            camera.fieldOfView = 38f;
            camera.transform.position = new Vector3(0f, 1.65f, -7.2f);
            camera.transform.LookAt(new Vector3(0f, 0.85f, 0f));
        }

        public void Dispose()
        {
            if (_root != null)
                UnityEngine.Object.Destroy(_root);
            _root = null;
            foreach (var material in _materials)
            {
                if (material != null)
                    UnityEngine.Object.Destroy(material);
            }
            _materials.Clear();
        }

        private void AddBackdrop()
        {
            AddBox(
                "ShowcaseFloor",
                new Vector3(0f, -0.08f, 0.3f),
                new Vector3(8f, 0.12f, 4f),
                new Color(0.12f, 0.15f, 0.20f));
            AddBox(
                "ShowcaseBackWall",
                new Vector3(0f, 1.75f, 1.25f),
                new Vector3(8f, 3.7f, 0.10f),
                new Color(0.07f, 0.09f, 0.13f));
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
