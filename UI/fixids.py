import json

with open('airspace/airspaces7.geojson') as json_data:
    data = json.load(json_data)
    json_data.close()
    outfile = {"type": "FeatureCollection","name": "testwave","crs": { "type": "name", "properties": { "name": "urn:ogc:def:crs:OGC:1.3:CRS84" } },"features":[]}
    
    #print(data["features"][0]["geometry"]["coordinates"])
    i = 0
    for f in data["features"]:
        thisfeature = f
        thisfeature["properties"]["id"] = i
        outfile["features"].append(thisfeature)

        i +=1
#print(outfile)
json_object = json.dumps(outfile)

# Writing to sample.json
with open("airspace/airspaces7Fixed.geojson", "w") as outfile:
    outfile.write(json_object)