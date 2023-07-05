import csv, os, math, boto3, datetime, time, json
import urllib.request
import requests
from PIL import Image, ImageDraw, ImageChops
import numpy as np
import osmnx as ox
import pandas as pd
import geopandas as gpd
import utm
from shapely.geometry import Point, LineString
from shapely.ops import linemerge

def calculate_initial_compass_bearing(pointA, pointB):
    if (type(pointA) != tuple) or (type(pointB) != tuple):
        raise TypeError("Only tuples are supported as arguments")
    lat1 = math.radians(pointA[0])
    lat2 = math.radians(pointB[0])
    diffLong = math.radians(pointB[1] - pointA[1])
    x = math.sin(diffLong) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - (math.sin(lat1)
            * math.cos(lat2) * math.cos(diffLong))
    initial_bearing = math.atan2(x, y)
    initial_bearing = math.degrees(initial_bearing)
    compass_bearing = (initial_bearing + 360) % 360
    return compass_bearing

def extract_street_network_data(place_name="Hampstead, Urban agglomeration of Montreal, Montreal (administrative region), Quebec, Canada",
                                buffer_sizes=(200, 5),
                                point_sampling_distance=1,
                                allowed_highways=["residential", "tertiary", "secondary", "primary", "unclassified"],
                                source_crs = "EPSG:4326",
                                output_filename="osm_points.csv"):
    
    # Get the latitude and longitude for a place
    location = ox.geocode(place_name)
    lat, lon = location

    # Get the UTM zone for the place
    _, _, zone_number, zone_letter = utm.from_latlon(lat, lon)

    # Construct the EPSG code for the UTM zone
    target_crs = f"EPSG:{32600 + zone_number if lat >= 0 else 32700 + zone_number}"

    print(str(target_crs))

    polygon = ox.geocode_to_gdf(place_name)
    polygon_proj = polygon.to_crs(target_crs)

    buffered_polygon_proj_large = polygon_proj.geometry.buffer(buffer_sizes[0])
    buffered_polygon_proj_small = polygon_proj.geometry.buffer(buffer_sizes[1])

    buffered_polygon_large = buffered_polygon_proj_large.to_crs(source_crs)
    buffered_polygon_small = buffered_polygon_proj_small.to_crs(source_crs)

    buffered_polygon_large = buffered_polygon_large.unary_union
    buffered_polygon_small = buffered_polygon_small.unary_union

    G = ox.graph_from_polygon(buffered_polygon_large, network_type="drive", retain_all=True)

    streets = ox.graph_to_gdfs(G, nodes=False, edges=True)
    streets = streets.loc[:, ["osmid", "name", "highway", "geometry"]]
    streets["osmid"] = streets["osmid"].astype(str)
    streets = streets[streets["highway"].isin(allowed_highways)]
    streets = streets[streets["geometry"].intersects(buffered_polygon_small) | streets["geometry"].within(buffered_polygon_small)]
    streets = streets.drop_duplicates(subset = "geometry")

    merged_streets = streets.groupby("osmid").agg({"name": "first", "highway": "first", "geometry": lambda x: linemerge(x.tolist())}).reset_index()
    merged_streets_gdf = gpd.GeoDataFrame(merged_streets, geometry="geometry", crs=source_crs)
    streets_proj = merged_streets_gdf.to_crs(target_crs)

    points_proj = gpd.GeoDataFrame(columns=["osmid", "index", "name", "highway", "X_Meters", "Y_Meters", "Heading", "geometry"])

    for idx, row in streets_proj.iterrows():
        street_line = row["geometry"]
        length = street_line.length
        num_points = round(length)

        sampled_points_proj = [street_line.interpolate(i) for i in range(0, num_points, point_sampling_distance)]

        point_geometries = [Point(point.coords[0]) for point in sampled_points_proj]

        X_Meters = np.array([point.x for point in sampled_points_proj])
        Y_Meters = np.array([point.y for point in sampled_points_proj])

        # New Heading calculation:
        # Transform X_Meters and Y_Meters back to lat/lon for bearing calculation
        LatLonPoints = [utm.to_latlon(x, y, zone_number, zone_letter) for x, y in zip(X_Meters, Y_Meters)]
        
        # Calculate the bearings
        Heading = [calculate_initial_compass_bearing(LatLonPoints[i], LatLonPoints[i+1]) for i in range(len(LatLonPoints)-1)]
        
        # As the first point does not have a previous point to calculate the bearing with,
        # we will just duplicate the first calculated bearing
        Heading = [Heading[0]] + Heading

        point_data = pd.DataFrame({
            "osmid": [row["osmid"]] * num_points,
            "index": range(num_points),
            "name": [row["name"]] * num_points,
            "highway": [row["highway"]] * num_points,
            "X_Meters": X_Meters,
            "Y_Meters": Y_Meters,
            "Heading": Heading,
        })

        points_gdf = gpd.GeoDataFrame(point_data, geometry=point_geometries, crs=target_crs)
        points_proj = points_proj._append(points_gdf, ignore_index=True)

    points_proj.reset_index(drop=True, inplace=True)

    points = points_proj.to_crs(source_crs)
    points["X"] = points.geometry.x
    points["Y"] = points.geometry.y
    #points = points.rename(columns={"index": "Node"}, errors="raise")
    points = points.drop("geometry", axis=1)

    points.to_csv(output_filename, index=False)

    print(f"CSV file '{output_filename}' exported successfully.")



placeName = "Hampstead, Urban agglomeration of Montreal, Montreal (administrative region), Quebec, Canada"


extract_street_network_data(place_name=placeName)
