import json

with open('airspace/asCTR.geojson') as json_data:
    data = json.load(json_data)
    json_data.close()
    outfile = {"type": "FeatureCollection","name": "testwave","crs": { "type": "name", "properties": { "name": "urn:ogc:def:crs:OGC:1.3:CRS84" } },"features":[]}
    
    #print(data["features"][0]["geometry"]["coordinates"])
    i = 0
    for f in data["features"]:
        thisfeature = {"type": "Feature","properties":{"Name":"", "id":i, "low":0,"up":0}}
        polys = f["geometry"]["coordinates"]
        hasdifferentAltitude = False
        lowerbound = 0
        upperbound = 0
        print("newfeature")
        lastz = 0
        if f["geometry"]["type"] == "MultiPolygon" :
            for x in f["geometry"]["coordinates"]:
                for p in x[0]:
                    #print(p)

                    if p[2] != lastz:
                        #print(p[2])
                        
                    
                    
                    
                        
                        if p[2] > lastz:
                                upperbound = p[2]
                                lowerbound = lastz
                                #print(str(upperbound)+ "  "+str(lowerbound))
                        else:
                                lowerbound = p[2]
                                upperbound = lastz
                                
                        lastz = p[2]
        else:
            upperbound = f["geometry"]["coordinates"][0][0][2]   
            
        print(str(upperbound)+ "  "+str(lowerbound))
        if lowerbound < 15000:
            n = f["properties"]["Name"].split("(")
            thisfeature["properties"]["Name"] = n[0]
            thisfeature["properties"]["low"] = int(lowerbound)
            thisfeature["properties"]["up"] = int(upperbound)
            thisfeature["geometry"] = f["geometry"]
            #if i < 2:
            outfile["features"].append(thisfeature)
        
            
        i +=1
#print(outfile)
json_object = json.dumps(outfile)

# Writing to sample.json
with open("airspace/asCTRn.geojson", "w") as outfile:
    outfile.write(json_object)

