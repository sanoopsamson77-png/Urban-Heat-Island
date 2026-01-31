from flask import Flask, request, jsonify, render_template
import ee
import os
import statistics

# Initialize Earth Engine
ee.Initialize(project="driven-airway-478206-j1")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates")
)

# ---------------- HOME ----------------
@app.route("/")
def home():
    return render_template("index.html")

# ---------------- CORE LST FUNCTION ----------------
def get_lst(lat, lon, start_date, end_date):
    point = ee.Geometry.Point([lon, lat])

    collection = (
        ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
        .filterBounds(point)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lt("CLOUD_COVER", 20))
        .sort("CLOUD_COVER")
    )

    if collection.size().getInfo() == 0:
        return None

    image = ee.Image(collection.first())

    lst = (
        image.select("ST_B10")
        .multiply(0.00341802)
        .add(149.0)
        .subtract(273.15)
    )

    value = lst.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=point,
        scale=30
    ).get("ST_B10")

    return value.getInfo()

# ---------------- NDVI FUNCTION ----------------
def get_ndvi(lat, lon, start_date, end_date):
    point = ee.Geometry.Point([lon, lat])

    collection = (
        ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
        .filterBounds(point)
        .filterDate(start_date, end_date)
        .filter(ee.Filter.lt("CLOUD_COVER", 20))
        .sort("CLOUD_COVER")
    )

    if collection.size().getInfo() == 0:
        return None

    image = ee.Image(collection.first())

    # Calculate NDVI: (NIR - Red) / (NIR + Red)
    # Landsat 8: NIR = B5, Red = B4
    nir = image.select("SR_B5").multiply(0.0000275).add(-0.2)
    red = image.select("SR_B4").multiply(0.0000275).add(-0.2)
    ndvi = nir.subtract(red).divide(nir.add(red))

    value = ndvi.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=point,
        scale=30
    ).get("SR_B5")

    return value.getInfo()

# ---------------- HEAT STRESS CATEGORIZATION ----------------
def categorize_heat_stress(temp):
    """Categorize temperature into heat stress levels"""
    if temp is None:
        return None
    if temp < 30:
        return {"level": "Low", "color": "#22c55e", "risk": "Minimal heat-related health risks"}
    elif temp < 38:
        return {"level": "Moderate", "color": "#eab308", "risk": "Caution advised for prolonged outdoor activities"}
    elif temp < 45:
        return {"level": "High", "color": "#f97316", "risk": "Heat exhaustion possible with extended exposure"}
    else:
        return {"level": "Extreme", "color": "#ef4444", "risk": "Heat stroke risk - limit outdoor activities"}

# ---------------- RECOMMENDATIONS GENERATOR ----------------
def generate_recommendations(temp, ndvi):
    """Generate urban planning recommendations based on temperature and NDVI"""
    recommendations = []
    priority = "Low"
    
    if temp is None:
        return {"priority": priority, "recommendations": []}
    
    # Temperature-based recommendations
    if temp >= 40:
        priority = "Critical"
        recommendations.extend([
            {"icon": "🌳", "title": "Urgent Urban Forestry", "desc": "High priority for immediate tree planting programs to provide shade and evaporative cooling."},
            {"icon": "🏗️", "title": "Cool Pavement Implementation", "desc": "Replace dark asphalt with reflective or permeable cool pavements to reduce heat absorption."},
            {"icon": "🏠", "title": "Green Roof Mandate", "desc": "Implement green roof requirements for new and existing buildings in this zone."},
            {"icon": "💧", "title": "Water Features", "desc": "Install fountains, misting systems, or urban water bodies for localized cooling."},
        ])
    elif temp >= 35:
        priority = "High"
        recommendations.extend([
            {"icon": "🌳", "title": "Urban Forestry Priority", "desc": "Recommended zone for tree planting initiatives and urban greening projects."},
            {"icon": "🏗️", "title": "Cool Materials", "desc": "Encourage use of high-albedo roofing and wall materials in construction."},
            {"icon": "🏠", "title": "Green Infrastructure", "desc": "Promote green roofs, vertical gardens, and permeable surfaces."},
        ])
    elif temp >= 30:
        priority = "Moderate"
        recommendations.extend([
            {"icon": "🌿", "title": "Vegetation Enhancement", "desc": "Increase vegetation cover through parks and street plantings."},
            {"icon": "🏢", "title": "Building Guidelines", "desc": "Recommend reflective building materials for new constructions."},
        ])
    else:
        priority = "Low"
        recommendations.append(
            {"icon": "✅", "title": "Maintain Current Conditions", "desc": "Temperature levels are within comfortable range. Focus on preservation."}
        )
    
    # NDVI-based recommendations (if available)
    if ndvi is not None:
        if ndvi < 0.2:
            recommendations.append(
                {"icon": "🚨", "title": "Critical Vegetation Deficit", "desc": f"NDVI: {ndvi:.2f} - Severely limited vegetation. Urgent need for green space development."}
            )
        elif ndvi < 0.4:
            recommendations.append(
                {"icon": "⚠️", "title": "Low Vegetation Cover", "desc": f"NDVI: {ndvi:.2f} - Below optimal vegetation levels. Recommend increased planting."}
            )
    
    return {"priority": priority, "recommendations": recommendations}

# ---------------- POINT LST ----------------
@app.route("/lst", methods=["POST"])
def lst_api():
    data = request.json

    lst = get_lst(
        data["lat"],
        data["lon"],
        data["start"],
        data["end"]
    )

    if lst is None:
        return jsonify({"error": "No valid data"}), 404

    # Get NDVI for the same point
    ndvi = get_ndvi(data["lat"], data["lon"], data["start"], data["end"])
    
    # Get heat stress category
    heat_stress = categorize_heat_stress(lst)
    
    # Generate recommendations
    recommendations = generate_recommendations(lst, ndvi)

    return jsonify({
        "lst_celsius": round(lst, 2),
        "ndvi": round(ndvi, 3) if ndvi else None,
        "heat_stress": heat_stress,
        "recommendations": recommendations
    })

# ---------------- HEATMAP WITH UHI DETECTION ----------------
@app.route("/heatmap", methods=["POST"])
def heatmap_api():
    data = request.json

    lat = data["lat"]
    lon = data["lon"]
    start = data["start"]
    end = data["end"]

    points = []
    temps = []
    raw_data = []

    # 7x7 grid around clicked point for better UHI detection
    offsets = [-0.03, -0.02, -0.01, 0, 0.01, 0.02, 0.03]
    
    for dx in offsets:
        for dy in offsets:
            try:
                point_lat = lat + dx
                point_lon = lon + dy
                lst = get_lst(point_lat, point_lon, start, end)
                if lst is not None:
                    temps.append(lst)
                    raw_data.append({"lat": point_lat, "lon": point_lon, "temp": lst})
                    # normalize intensity to 0–1 (20°C = cool, 50°C = hot)
                    intensity = min(max((lst - 20) / 30, 0), 1)
                    points.append([point_lat, point_lon, intensity])
            except Exception:
                continue

    if not points:
        return jsonify({"error": "No valid data found for this area"}), 404

    # Calculate statistics for UHI detection
    avg_temp = sum(temps) / len(temps)
    std_dev = statistics.stdev(temps) if len(temps) > 1 else 0
    
    # UHI Detection: Points significantly warmer than surroundings (> 1.5 std dev above mean)
    uhi_threshold = avg_temp + (1.5 * std_dev) if std_dev > 0 else avg_temp + 2
    uhi_hotspots = []
    
    for point_data in raw_data:
        if point_data["temp"] >= uhi_threshold:
            heat_stress = categorize_heat_stress(point_data["temp"])
            uhi_hotspots.append({
                "lat": point_data["lat"],
                "lon": point_data["lon"],
                "temp": round(point_data["temp"], 2),
                "deviation": round(point_data["temp"] - avg_temp, 2),
                "heat_stress": heat_stress
            })
    
    # Sort hotspots by temperature (hottest first)
    uhi_hotspots.sort(key=lambda x: x["temp"], reverse=True)
    
    # Generate area-wide recommendations based on max temp
    max_temp = max(temps)
    recommendations = generate_recommendations(max_temp, None)
    
    # Categorize all points by heat stress
    heat_stress_summary = {"Low": 0, "Moderate": 0, "High": 0, "Extreme": 0}
    for t in temps:
        cat = categorize_heat_stress(t)
        if cat:
            heat_stress_summary[cat["level"]] += 1

    return jsonify({
        "points": points,
        "stats": {
            "count": len(points),
            "min_temp": round(min(temps), 2),
            "max_temp": round(max(temps), 2),
            "avg_temp": round(avg_temp, 2),
            "std_dev": round(std_dev, 2),
            "uhi_threshold": round(uhi_threshold, 2)
        },
        "uhi_hotspots": uhi_hotspots,
        "heat_stress_summary": heat_stress_summary,
        "recommendations": recommendations
    })

# ---------------- NDVI LAYER ----------------
@app.route("/ndvi", methods=["POST"])
def ndvi_api():
    data = request.json

    lat = data["lat"]
    lon = data["lon"]
    start = data["start"]
    end = data["end"]

    points = []
    ndvi_values = []

    # 7x7 grid matching heatmap
    offsets = [-0.03, -0.02, -0.01, 0, 0.01, 0.02, 0.03]
    
    for dx in offsets:
        for dy in offsets:
            try:
                point_lat = lat + dx
                point_lon = lon + dy
                ndvi = get_ndvi(point_lat, point_lon, start, end)
                if ndvi is not None:
                    ndvi_values.append(ndvi)
                    # NDVI ranges from -1 to 1, normalize to 0-1 for display
                    # Higher NDVI (more vegetation) = green, Lower = brown/red
                    intensity = max(0, min(1, (ndvi + 0.2) / 0.8))
                    points.append({
                        "lat": point_lat,
                        "lon": point_lon,
                        "ndvi": round(ndvi, 3),
                        "intensity": intensity
                    })
            except Exception:
                continue

    if not points:
        return jsonify({"error": "No valid NDVI data found"}), 404

    # Categorize vegetation coverage
    avg_ndvi = sum(ndvi_values) / len(ndvi_values)
    
    if avg_ndvi < 0.1:
        veg_status = {"level": "Barren/Built-up", "color": "#ef4444", "desc": "Minimal vegetation - likely urban/built-up area"}
    elif avg_ndvi < 0.2:
        veg_status = {"level": "Sparse", "color": "#f97316", "desc": "Very sparse vegetation cover"}
    elif avg_ndvi < 0.4:
        veg_status = {"level": "Moderate", "color": "#eab308", "desc": "Moderate vegetation - mixed urban/green"}
    elif avg_ndvi < 0.6:
        veg_status = {"level": "Good", "color": "#84cc16", "desc": "Good vegetation cover - parks/suburbs"}
    else:
        veg_status = {"level": "Dense", "color": "#22c55e", "desc": "Dense vegetation - forest/agricultural"}

    return jsonify({
        "points": points,
        "stats": {
            "count": len(points),
            "min_ndvi": round(min(ndvi_values), 3),
            "max_ndvi": round(max(ndvi_values), 3),
            "avg_ndvi": round(avg_ndvi, 3)
        },
        "vegetation_status": veg_status
    })

# ---------------- CORRELATION ANALYSIS ----------------
@app.route("/correlation", methods=["POST"])
def correlation_api():
    """Analyze correlation between LST and NDVI"""
    data = request.json

    lat = data["lat"]
    lon = data["lon"]
    start = data["start"]
    end = data["end"]

    paired_data = []
    offsets = [-0.03, -0.02, -0.01, 0, 0.01, 0.02, 0.03]
    
    for dx in offsets:
        for dy in offsets:
            try:
                point_lat = lat + dx
                point_lon = lon + dy
                lst = get_lst(point_lat, point_lon, start, end)
                ndvi = get_ndvi(point_lat, point_lon, start, end)
                if lst is not None and ndvi is not None:
                    heat_stress = categorize_heat_stress(lst)
                    paired_data.append({
                        "lat": point_lat,
                        "lon": point_lon,
                        "lst": round(lst, 2),
                        "ndvi": round(ndvi, 3),
                        "heat_stress": heat_stress["level"]
                    })
            except Exception:
                continue

    if len(paired_data) < 3:
        return jsonify({"error": "Insufficient data for correlation analysis"}), 404

    # Calculate Pearson correlation coefficient
    lst_values = [d["lst"] for d in paired_data]
    ndvi_values = [d["ndvi"] for d in paired_data]
    
    n = len(paired_data)
    mean_lst = sum(lst_values) / n
    mean_ndvi = sum(ndvi_values) / n
    
    numerator = sum((lst_values[i] - mean_lst) * (ndvi_values[i] - mean_ndvi) for i in range(n))
    denom_lst = sum((x - mean_lst) ** 2 for x in lst_values) ** 0.5
    denom_ndvi = sum((x - mean_ndvi) ** 2 for x in ndvi_values) ** 0.5
    
    correlation = numerator / (denom_lst * denom_ndvi) if denom_lst * denom_ndvi != 0 else 0
    
    # Interpret correlation
    if correlation < -0.7:
        interpretation = "Strong negative correlation: Higher vegetation strongly associated with lower temperatures"
    elif correlation < -0.4:
        interpretation = "Moderate negative correlation: Vegetation helps reduce surface temperatures"
    elif correlation < -0.2:
        interpretation = "Weak negative correlation: Some cooling effect from vegetation observed"
    elif correlation < 0.2:
        interpretation = "No significant correlation detected in this area"
    else:
        interpretation = "Unexpected positive correlation - may indicate data quality issues or unique local conditions"

    return jsonify({
        "data": paired_data,
        "correlation": round(correlation, 3),
        "interpretation": interpretation,
        "stats": {
            "mean_lst": round(mean_lst, 2),
            "mean_ndvi": round(mean_ndvi, 3),
            "sample_size": n
        }
    })

#  RUN 
if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
