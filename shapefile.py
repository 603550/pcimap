import math
import osmnx as ox
import pandas as pd
import geopandas as gpd
from shapely.geometry import Point, LineString
from shapely.ops import linemerge

# Define the place name or OSM Relation ID
place_name = "R197569"

# CRS Info
source_crs = "EPSG:4326"
target_crs = "EPSG:32188"

# Retrieve the polygon using osmnx
polygon = ox.geocode_to_gdf(place_name)

# Reproject the polygon to target_crs for buffering
polygon_proj = polygon.to_crs(target_crs)

# Add a buffer around the projected polygon (e.g., 200 meters)
buffered_polygon_proj_large = polygon_proj.geometry.buffer(200)
buffered_polygon_proj_small = polygon_proj.geometry.buffer(5)

# Reproject the buffered polygon back to source_crs
buffered_polygon_large = buffered_polygon_proj_large.to_crs(source_crs)
buffered_polygon_small = buffered_polygon_proj_small.to_crs(source_crs)

# Convert the buffered polygon to a single Polygon object
buffered_polygon_large = buffered_polygon_large.unary_union
buffered_polygon_small = buffered_polygon_small.unary_union

# Retrieve the street network within the buffered polygon
G = ox.graph_from_polygon(buffered_polygon_large, network_type="all")

# Convert the street network to a GeoDataFrame
streets = ox.graph_to_gdfs(G, nodes=False, edges=True)

# Select specific columns in the GeoDataFrame
streets = streets.loc[:, ["osmid", "name", "highway", "geometry"]]

# Convert osmid to string
streets["osmid"] = streets["osmid"].astype(str)

# Filter the streets based on specific highway values
allowed_highways = ["residential", "tertiary", "secondary", "primary", "unclassified"]
streets = streets[streets["highway"].isin(allowed_highways)]

# Filter the streets that intersect or are within the original polygon
streets = streets[streets["geometry"].intersects(buffered_polygon_small) | streets["geometry"].within(buffered_polygon_small)]

# Drop duplicates
streets = streets.drop_duplicates(subset = "geometry")

# Merge linestrings with the same osmid into a single linestring
merged_streets = streets.groupby("osmid").agg({"name": "first", "highway": "first", "geometry": lambda x: linemerge(x.tolist())}).reset_index()

# Create a GeoDataFrame with the merged streets
merged_streets_gdf = gpd.GeoDataFrame(merged_streets, geometry="geometry", crs=source_crs)

# Reproject to the target CRS
streets_proj = merged_streets_gdf.to_crs(target_crs)

# Create an empty GeoDataFrame to store the sampled points
points_proj = gpd.GeoDataFrame(columns=["osmid", "index", "name", "highway", "X_Meters", "Y_Meters", "Heading", "geometry"])

# Iterate over each street line and sample points at 1m distance
for idx, row in streets_proj.iterrows():
    street_line = row["geometry"]
    length = street_line.length
    num_points = round(length)  # Number of points to sample

    # Sample points at 1m distance along the street line
    sampled_points_proj = [street_line.interpolate(i) for i in range(0, num_points, 1)]

    # Create Point geometries for the sampled points
    point_geometries = [Point(point.coords[0]) for point in sampled_points_proj]

    # Create a DataFrame with the point attributes
    point_data = pd.DataFrame({
        "osmid": [row["osmid"]] * num_points,
        "index": range(num_points),
        "name": [row["name"]] * num_points,
        "highway": [row["highway"]] * num_points,
        "X_Meters": [point.x for point in sampled_points_proj],
        "Y_Meters": [point.y for point in sampled_points_proj],
        "Heading": [0] * num_points,
    })

    # Calculate the heading on Cartesian coordinates
    for i in range(1, num_points):
        point_data.loc[i, "Heading"] = math.degrees(math.atan2(
            point_data.loc[i, "Y_Meters"] - point_data.loc[i - 1, "Y_Meters"],
            point_data.loc[i, "X_Meters"] - point_data.loc[i - 1, "X_Meters"]
        ))

    # Set the heading of the first point to match the second point
    point_data.loc[0, "Heading"] = point_data.loc[1, "Heading"]

    # Add 180 degrees
    point_data["Heading"] = point_data["Heading"] + 90

    # Create a GeoDataFrame from the point data and geometries
    points_gdf = gpd.GeoDataFrame(point_data, geometry=point_geometries, crs=target_crs)

    # Append the points to the main GeoDataFrame
    points_proj = points_proj._append(points_gdf, ignore_index=True)

# Reset the index of the points_proj GeoDataFrame
points_proj.reset_index(drop=True, inplace=True)

# Reproject to source_crs
points = points_proj.to_crs(source_crs)
points["X"] = points.geometry.x
points["Y"] = points.geometry.y

# Final format
points = points.rename(columns={"index": "Node"}, errors="raise")
points = points.drop("geometry", axis=1)

# Export the points to a CSV file
points.to_csv("sampled_points.csv", index=False)

# Print a confirmation message
print("CSV file exported successfully.")
