using System;
using System.IO;
using System.Threading.Tasks;
using GLTFast;
using UnityEngine;

namespace MetroReplay.Presentation
{
    public sealed class PassengerAvatarLoader : IDisposable
    {
        private const float TargetHeight = 1.68f;
        private GltfImport _import;
        private GameObject _prototype;

        public async Task<GameObject> LoadPrototypeAsync(string filePath)
        {
            if (string.IsNullOrWhiteSpace(filePath) || !File.Exists(filePath))
                throw new FileNotFoundException("Passenger GLB was not found.", filePath);
            if (_prototype != null)
                return _prototype;

            _import = new GltfImport(materialGenerator: new ReplayGltfMaterialGenerator());
            var settings = new ImportSettings
            {
                AnimationMethod = AnimationMethod.Legacy,
                NodeNameMethod = NameImportMethod.OriginalUnique,
                GenerateMipMaps = false
            };
            if (!await _import.LoadFile(filePath, importSettings: settings))
                throw new InvalidOperationException("glTFast could not load the passenger GLB.");

            var prototype = new GameObject("QuaterniusPassengerPrototype");
            var content = new GameObject("NormalizedAvatar");
            content.transform.SetParent(prototype.transform, false);
            var instantiator = new GameObjectInstantiator(_import, content.transform);
            if (!await _import.InstantiateMainSceneAsync(instantiator))
            {
                UnityEngine.Object.Destroy(prototype);
                throw new InvalidOperationException("glTFast could not instantiate the passenger scene.");
            }

            var renderers = content.GetComponentsInChildren<Renderer>(true);
            if (renderers.Length == 0)
            {
                UnityEngine.Object.Destroy(prototype);
                throw new InvalidOperationException("Passenger GLB contains no renderable mesh.");
            }

            NormalizeAvatar(content.transform, renderers);
            var animation = prototype.GetComponentInChildren<Animation>(true);
            if (animation == null)
            {
                UnityEngine.Object.Destroy(prototype);
                throw new InvalidOperationException("Passenger GLB contains no legacy animation component.");
            }
            ConfigureAnimation(animation);

            prototype.SetActive(false);
            _prototype = prototype;
            return prototype;
        }

        public void Dispose()
        {
            if (_prototype != null)
                UnityEngine.Object.Destroy(_prototype);
            _prototype = null;
            _import?.Dispose();
            _import = null;
        }

        private static void NormalizeAvatar(Transform content, Renderer[] renderers)
        {
            var bounds = renderers[0].bounds;
            for (var i = 1; i < renderers.Length; i++)
                bounds.Encapsulate(renderers[i].bounds);

            var scale = TargetHeight / Mathf.Max(bounds.size.y, 0.001f);
            content.localScale = Vector3.one * scale;
            content.localPosition = -bounds.center * scale;
        }

        private static void ConfigureAnimation(Animation animation)
        {
            animation.playAutomatically = false;
            animation.cullingType = AnimationCullingType.BasedOnRenderers;
            foreach (AnimationState state in animation)
                state.wrapMode = WrapMode.Loop;
        }

    }
}
