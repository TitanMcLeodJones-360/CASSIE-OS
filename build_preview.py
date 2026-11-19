"""Build the offline command-center preview and release integrity baseline."""
from pathlib import Path
import base64
import hashlib
import json

BASE = Path(__file__).resolve().parent
app = BASE/"app"
static = app/"static"
def main():
    out = BASE.parent/"output"
    out.mkdir(exist_ok=True)
    data = json.loads((app/"dataset_catalog.json").read_text())
    demo = {
        "entries":[r[:4] for r in data["entries"] if not r[4]],
        "notes":[{"id":1,"note":"Example owner note: TitanGame is the home node. Keep the 5 TB archive optional."}],
        "telemetry":{"machine":{"host":"TitanGame","storage_free_gib":91,"ram_available_gib":16.8,"ram_total_gib":19.4,
                      "cpu_c":43.2,"load_1min":0.41,"model_ready":True,"gpu":[{"name":"GeForce GTX 1650 SUPER","used_mib":598,"total_mib":4096}]},
            "bulk":{"mounted":False},"integrity":{"state":"ok","detail":"Simulated: no integrity issues."},"voice":True,
            "network":{"configured":True,"devices":[
                {"name":"Titan’s phone","ip":"10.77.0.51","mac":"02:00:00:00:00:51","state":"new","last_seen":None},
                {"name":"Lab sensor","ip":"10.77.0.61","mac":"02:00:00:00:00:61","state":"missing","last_seen":None}]}},
    }
    text = (static/"index.html").read_text()
    logo = base64.b64encode((static/"insignia.webp").read_bytes()).decode()
    text = text.replace('src="insignia.webp"', 'src="data:image/webp;base64,'+logo+'"')
    text = text.replace('<link rel="stylesheet" href="style.css">','<style>\n'+(static/"style.css").read_text()+'\n</style>')
    payload = json.dumps(demo,ensure_ascii=True,separators=(",",":")).replace("<",r"\u003c")
    text = text.replace('<script src="app.js"></script>','<script>window.CASSIE_PREVIEW='+payload+';\n'+(static/"app.js").read_text()+'\n</script>')
    (out/"CASSIE-Command-Preview.html").write_text(text)
    names = ("command_center.py","server.py","observer.py","speech.py","network_activity.py","base_persona.txt","static/app.js","static/mic-worklet.js","static/style.css","static/index.html","static/insignia.webp","dataset_catalog.json","dataset_search.py")
    (app/"integrity.json").write_text(json.dumps({name:hashlib.sha256((app/name).read_bytes()).hexdigest() for name in names},indent=2)+"\n")

if __name__=="__main__":
    main()
