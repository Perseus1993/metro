using System;
using System.Collections.Generic;
using UnityEngine;

namespace MetroReplay.Presentation
{
    public sealed class RocketboxPassengerLibrary
    {
        private const string ResourcePath = "PassengerBases/Generated/Prefabs";
        private readonly List<GameObject> _prototypes = new List<GameObject>();

        public IReadOnlyList<GameObject> Prototypes => _prototypes;
        public int BaseCount => _prototypes.Count;
        public int LodLevelCount { get; private set; }

        public static RocketboxPassengerLibrary Load()
        {
            var library = new RocketboxPassengerLibrary();
            var loaded = Resources.LoadAll<GameObject>(ResourcePath);
            Array.Sort(loaded, CompareByIdentity);
            foreach (var prototype in loaded)
            {
                var identity = prototype.GetComponent<PassengerBaseIdentity>();
                if (identity == null)
                    continue;
                library._prototypes.Add(prototype);
                library.LodLevelCount = Mathf.Max(library.LodLevelCount, identity.LodLevelCount);
            }
            return library;
        }

        private static int CompareByIdentity(GameObject left, GameObject right)
        {
            var leftId = left.GetComponent<PassengerBaseIdentity>()?.BaseId ?? left.name;
            var rightId = right.GetComponent<PassengerBaseIdentity>()?.BaseId ?? right.name;
            return string.Compare(leftId, rightId, StringComparison.Ordinal);
        }
    }
}
