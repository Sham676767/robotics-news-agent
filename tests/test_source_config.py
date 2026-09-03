from app.collector import load_sources


def test_ieee_spectrum_robotics_is_a_direct_configured_source():
    source = next(
        item for item in load_sources()
        if item["name"] == "IEEE Spectrum Robotics"
    )

    assert source["url"] == "https://spectrum.ieee.org/feeds/topic/robotics.rss"
    assert source["url"].startswith("https://")
    assert "robotics" in source["topics"]
