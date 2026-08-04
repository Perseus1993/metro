using System;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
using GLTFast;
using UnityEngine;

namespace MetroReplay.Presentation
{
    internal sealed class RuntimeGltfPrototypeLibrary : IDisposable
    {
        private sealed class Entry
        {
            public GltfImport Import;
            public GameObject Prototype;
        }

        private readonly Dictionary<string, Entry> _entries = new Dictionary<string, Entry>();

        public async Task LoadAsync(string key, string filePath)
        {
            if (_entries.ContainsKey(key))
                return;
            if (!File.Exists(filePath))
                throw new FileNotFoundException($"Decoration asset '{key}' was not found.", filePath);

            var import = new GltfImport(materialGenerator: new ReplayGltfMaterialGenerator());
            var settings = new ImportSettings
            {
                AnimationMethod = AnimationMethod.None,
                NodeNameMethod = NameImportMethod.OriginalUnique,
                GenerateMipMaps = true
            };
            var directory = Path.GetFullPath(Path.GetDirectoryName(filePath) ?? string.Empty)
                + Path.DirectorySeparatorChar;
            if (!await import.LoadFile(filePath, new Uri(directory), settings))
            {
                import.Dispose();
                throw new InvalidOperationException($"Could not load decoration asset '{key}'.");
            }

            var prototype = new GameObject("DecorationPrototype_" + key);
            var content = new GameObject("UnitHeightModel");
            content.transform.SetParent(prototype.transform, false);
            var instantiator = new GameObjectInstantiator(import, content.transform);
            if (!await import.InstantiateMainSceneAsync(instantiator))
            {
                UnityEngine.Object.Destroy(prototype);
                import.Dispose();
                throw new InvalidOperationException($"Could not instantiate decoration asset '{key}'.");
            }

            NormalizeToUnitHeight(content.transform);
            prototype.SetActive(false);
            _entries[key] = new Entry { Import = import, Prototype = prototype };
        }

        public GameObject Create(string key, Transform parent)
        {
            if (!_entries.TryGetValue(key, out var entry))
                throw new KeyNotFoundException($"Decoration asset '{key}' has not been loaded.");
            var instance = UnityEngine.Object.Instantiate(entry.Prototype, parent, false);
            instance.name = "Decoration_" + key;
            instance.SetActive(true);
            return instance;
        }

        public void Dispose()
        {
            foreach (var entry in _entries.Values)
            {
                if (entry.Prototype != null)
                    UnityEngine.Object.Destroy(entry.Prototype);
                entry.Import.Dispose();
            }
            _entries.Clear();
        }

        private static void NormalizeToUnitHeight(Transform content)
        {
            var renderers = content.GetComponentsInChildren<Renderer>(true);
            if (renderers.Length == 0)
                throw new InvalidOperationException("Decoration asset contains no renderable mesh.");
            var bounds = renderers[0].bounds;
            for (var i = 1; i < renderers.Length; i++)
                bounds.Encapsulate(renderers[i].bounds);

            var scale = 1f / Mathf.Max(bounds.size.y, 0.001f);
            content.localScale = Vector3.one * scale;
            content.localPosition = new Vector3(
                -bounds.center.x * scale,
                -bounds.min.y * scale,
                -bounds.center.z * scale);
        }
    }
}
