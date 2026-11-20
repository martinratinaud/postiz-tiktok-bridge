import json
p = "autotok/uploader.py"
s = open(p).read()
assert "allow_content_reuse" not in s
s = s.replace('''                "allow_comment": int(bool(allow_comment)),
            },
        }''', '''                "allow_comment": int(bool(allow_comment)),
                "allow_content_reuse": 1,
                "allow_ai_remix": 2,
            },
            "content_check_id": "",
        }''')
s = s.replace('''                    "music_info": {},
                    "poster_delay": 0,
                },''', '''                    "music_info": {"origin_volume": "100"},
                    "poster_delay": 0,
                    **_video_meta_fields(),
                },''')
helper = '''_CURRENT_META: dict = {}


def _probe(path) -> dict:
    import subprocess
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                              "stream=width,height:format=duration", "-of", "json", str(path)],
                             capture_output=True, text=True, timeout=30).stdout
        j = json.loads(out)
        st = j["streams"][0]
        aud = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index",
                              "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=30).stdout.strip()
        return {"w": int(st["width"]), "h": int(st["height"]),
                "ms": int(float(j["format"]["duration"]) * 1000), "audio": bool(aud)}
    except Exception:
        return {}


def _video_meta_fields() -> dict:
    m = _CURRENT_META
    if not m:
        return {}
    return {
        "cloud_edit_video_height": m["h"],
        "cloud_edit_video_width": m["w"],
        "cloud_edit_is_use_video_canvas": False,
        "has_original_audio": 1 if m["audio"] else 0,
        "is_upload_audio_track": False,
        "video_track_time_range_list": [{"start_time_in_ms": 0, "end_time_in_ms": m["ms"]}],
        "mature_theme_type": 0,
    }


'''
i = s.index("def _visibility(")
s = s[:i] + helper + s[i:]
s = s.replace('''        path = resolve_video_path(video)
''', '''        path = resolve_video_path(video)
        _CURRENT_META.clear()
        _CURRENT_META.update(_probe(path))
''', 1)
assert s.count("_video_meta_fields") == 2 and "_CURRENT_META.update" in s
open(p, "w").write(s)
print("patched")
