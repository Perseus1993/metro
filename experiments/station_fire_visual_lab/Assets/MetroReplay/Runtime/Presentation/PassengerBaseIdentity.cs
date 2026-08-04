using UnityEngine;

namespace MetroReplay.Presentation
{
    public sealed class PassengerBaseIdentity : MonoBehaviour
    {
        [SerializeField] private string baseId;
        [SerializeField] private int lodLevelCount;

        public string BaseId => baseId;
        public int LodLevelCount => lodLevelCount;

        public void Configure(string id, int lodLevels)
        {
            baseId = id;
            lodLevelCount = Mathf.Max(0, lodLevels);
        }
    }
}
