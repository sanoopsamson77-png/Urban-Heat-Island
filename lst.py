import ee

# Initialize Earth Engine
ee.Initialize(project="driven-airway-478206-j1")


def get_lst(lat, lon, start_date, end_date):
    point = ee.Geometry.Point([lon, lat])

    collection = (
        ee.ImageCollection("LANDSAT/LC08/C02/T1_L2")
        .filterBounds(point)
        .filterDate(start_date, end_date)
        .sort("CLOUD_COVER")
    )

    image = ee.Image(collection.first())

    lst = (
        image.select("ST_B10")
        .multiply(0.00341802)
        .add(149.0)
        .subtract(273.15)
    )

    mean_lst = lst.reduceRegion(
        reducer=ee.Reducer.mean(),
        geometry=point,
        scale=30,
        maxPixels=1e9
    )

    return mean_lst.getInfo()


def safe_get_lst(lat, lon, start_date, end_date):
    try:
        result = get_lst(lat, lon, start_date, end_date)
        if not result or "ST_B10" not in result:
            return {"error": "No valid LST data"}
        return {"lst_celsius": result["ST_B10"]}
    except Exception as e:
        return {"error": str(e)}
