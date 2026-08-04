using System.Linq;
using UnityEditor;
using UnityEngine;

namespace MetroReplay.Editor
{
    public static class RocketboxAssetInspector
    {
        [MenuItem("Metro Replay/Inspect Rocketbox")]
        public static void Inspect()
        {
            const string path = "Assets/Resources/PassengerBases/Rocketbox/Female_Adult_01/Export/Female_Adult_01.fbx";
            AssetDatabase.ImportAsset(path, ImportAssetOptions.ForceUpdate);
            var model = AssetDatabase.LoadAssetAtPath<GameObject>(path);
            if (model == null)
                throw new System.InvalidOperationException("Rocketbox model did not import: " + path);
            Debug.Log($"ROCKETBOX_ROOT={model.name};ANIMATOR={model.GetComponent<Animator>() != null}");
            foreach (var renderer in model.GetComponentsInChildren<Renderer>(true))
            {
                var vertices = renderer is SkinnedMeshRenderer skinned && skinned.sharedMesh != null
                    ? skinned.sharedMesh.vertexCount
                    : 0;
                var materials = string.Join(",", renderer.sharedMaterials.Select(item => item == null ? "null" : item.name));
                Debug.Log($"ROCKETBOX_RENDERER={Hierarchy(renderer.transform)};VERTICES={vertices};MATERIALS={materials};ACTIVE={renderer.gameObject.activeSelf}");
            }
            foreach (var asset in AssetDatabase.LoadAllAssetsAtPath(path))
            {
                if (asset is Mesh mesh)
                    Debug.Log($"ROCKETBOX_MESH={mesh.name};VERTICES={mesh.vertexCount};BONES={mesh.bindposes.Length}");
            }
            EditorApplication.Exit(0);
        }

        private static string Hierarchy(Transform item)
        {
            var result = item.name;
            while (item.parent != null)
            {
                item = item.parent;
                result = item.name + "/" + result;
            }
            return result;
        }
    }
}
