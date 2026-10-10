from pathlib import Path
import json
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jiji.engine import convert_file, office_binary

root = Path("output/fixtures")
report = {"engine": office_binary(), "files": []}
for suffix in ("docx", "xlsx", "pptx"):
    source = root / ("sample." + suffix)
    with convert_file(source.name, source.read_bytes()) as doc:
        target = root / (suffix + "-converted.pdf")
        target.write_bytes(doc.tobytes())
        text = "\n".join(p.get_text() for p in doc)
        assert "吉吉" in text, (suffix, text)
        if suffix == "xlsx":
            assert "30" in text, text
        doc[0].get_pixmap().save(root / (suffix + "-preview.png"))
        report["files"].append({"input": source.name, "pages": len(doc), "chineseText": True, "formulaRecalculated": suffix == "xlsx", "output": str(target)})
Path("output/office-verification.json").write_text(json.dumps(report, indent=2, ensure_ascii=False))
print(json.dumps(report, ensure_ascii=False))
