using UnityEngine;

namespace MetroReplay.Presentation
{
    [DisallowMultipleComponent]
    public sealed class VisualOnlyStationAssetIdentity : MonoBehaviour
    {
        [SerializeField] private string assetId;
        [SerializeField] private string source;
        [SerializeField] private string licence;

        public string AssetId => assetId;
        public string Source => source;
        public string Licence => licence;
        public bool AffectsSimulation => false;

        public void Configure(string id, string sourceName, string licenceName)
        {
            assetId = id;
            source = sourceName;
            licence = licenceName;
        }
    }
}
