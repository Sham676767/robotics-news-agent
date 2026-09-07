from app.collector import load_sources


def test_ieee_spectrum_robotics_is_a_direct_configured_source():
    source = next(
        item for item in load_sources()
        if item["name"] == "IEEE Spectrum Robotics"
    )

    assert source["url"] == "https://spectrum.ieee.org/feeds/topic/robotics.rss"
    assert source["url"].startswith("https://")
    assert "robotics" in source["topics"]


def test_expanded_topic_feeds_are_configured_over_https():
    names = {
        "Google News Social Robots",
        "Google News Physical AI",
        "Google News Humanoid Robot Launches",
        "Google News Humanoid Robot Funding",
        "Google News Quadruped Robots",
        "Google News Exoskeleton Technology",
        "Google News Consumer Exoskeletons",
        "Google News Social Robot Research",
        "Google News Companion Robots",
        "Google News Embodied AI Robotics",
        "Google News Robot Learning",
    }
    sources = {item["name"]: item for item in load_sources()}

    assert names.issubset(sources)
    assert len(sources) >= 27
    assert all(sources[name]["url"].startswith("https://") for name in names)
    assert sources["RoboBrief"]["url"] == "https://robobrief.tech/feed.xml"
