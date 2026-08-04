using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using UnityEditor;
using UnityEngine;

namespace HazardAssetLab.EditorTools
{
    public static class ValidateDownloadedAnimationAssets
    {
        private const string AssetRoot = "Assets/HazardAssetLab/ThirdParty/Quaternius/UniversalAnimationLibrary2Standard";
        private const string ReportPath = "Assets/HazardAssetLab/Reports/UniversalAnimationLibrary2_Validation.md";

        private static readonly string[] ModelPaths =
        {
            AssetRoot + "/UAL2_Standard.fbx",
            AssetRoot + "/UAL2_Standard_RM.fbx",
            AssetRoot + "/Mannequin_F.fbx"
        };

        private static readonly string[] PanicKeywords =
        {
            "panic", "scared", "fear", "flee", "escape", "run", "sprint", "stumble", "trip"
        };

        [MenuItem("Hazard Asset Lab/Validate Downloaded Animation Assets")]
        public static void Run()
        {
            try
            {
                EnsureFolder("Assets/HazardAssetLab/Reports");
                AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);

                var report = new StringBuilder();
                report.AppendLine("# Universal Animation Library 2 validation");
                report.AppendLine();
                report.AppendLine($"Validated: {DateTime.Now:yyyy-MM-dd HH:mm:ss}");
                report.AppendLine("License: CC0 1.0 (see bundled `License.txt`)");
                report.AppendLine();

                int totalClips = 0;
                var panicCandidates = new SortedSet<string>(StringComparer.OrdinalIgnoreCase);

                foreach (string path in ModelPaths)
                {
                    report.AppendLine($"## `{Path.GetFileName(path)}`");

                    var importer = AssetImporter.GetAtPath(path) as ModelImporter;
                    if (importer == null)
                    {
                        report.AppendLine("- ERROR: Unity did not create a ModelImporter.");
                        report.AppendLine();
                        continue;
                    }

                    AnimationClip[] clips = AssetDatabase.LoadAllAssetsAtPath(path)
                        .OfType<AnimationClip>()
                        .Where(clip => !clip.name.StartsWith("__preview__", StringComparison.OrdinalIgnoreCase))
                        .OrderBy(clip => clip.name, StringComparer.OrdinalIgnoreCase)
                        .ToArray();

                    totalClips += clips.Length;
                    foreach (AnimationClip clip in clips)
                    {
                        if (PanicKeywords.Any(keyword => clip.name.IndexOf(keyword, StringComparison.OrdinalIgnoreCase) >= 0))
                        {
                            panicCandidates.Add(clip.name);
                        }
                    }

                    report.AppendLine($"- Animation type: `{importer.animationType}`");
                    report.AppendLine($"- Import animation: `{importer.importAnimation}`");
                    report.AppendLine($"- Root motion source: `{importer.motionNodeName}`");
                    report.AppendLine($"- Clips found: {clips.Length}");
                    report.AppendLine("- Clip names:");
                    foreach (AnimationClip clip in clips)
                    {
                        report.AppendLine($"  - `{clip.name}` ({clip.length:0.###} s, {clip.frameRate:0.##} fps, loop={clip.isLooping})");
                    }
                    report.AppendLine();
                }

                report.AppendLine("## Panic/run candidate clips");
                if (panicCandidates.Count == 0)
                {
                    report.AppendLine("No clip name matched the panic/run keyword screen.");
                }
                else
                {
                    foreach (string clipName in panicCandidates)
                    {
                        report.AppendLine($"- `{clipName}`");
                    }
                }

                string absoluteReportPath = Path.GetFullPath(ReportPath);
                File.WriteAllText(absoluteReportPath, report.ToString(), Encoding.UTF8);
                AssetDatabase.Refresh(ImportAssetOptions.ForceSynchronousImport);

                Debug.Log($"[HazardAssetLab] UAL2 validation complete. totalClips={totalClips}, panicCandidates={panicCandidates.Count}, report={ReportPath}");
            }
            catch (Exception exception)
            {
                Debug.LogException(exception);
                if (Application.isBatchMode)
                {
                    EditorApplication.Exit(1);
                }
            }
        }

        private static void EnsureFolder(string path)
        {
            if (AssetDatabase.IsValidFolder(path)) return;
            string parent = Path.GetDirectoryName(path)?.Replace('\\', '/');
            string folder = Path.GetFileName(path);
            if (!string.IsNullOrEmpty(parent)) EnsureFolder(parent);
            AssetDatabase.CreateFolder(parent, folder);
        }
    }
}
