local data = {}

local ae_durations = {
    ["AE_Transform_21-trs"] = {{0, 1},},
    ["LumiLayerBlend_21-blend"] = {{0, 1},},
    ["LumiDirectionBlur_208-effect0"] = {{0.666667, 2.53333},},
    ["lumi_motion_blur_2d_208-effect1"] = {{0.666667, 2.53333},},
    ["LumiLayerBlend_208-blend"] = {{0.666667, 2.53333},},
    ["AE_Transform_210-effect0"] = {{0.666667, 2.33333},},
    ["LumiLayerBlend_210-blend"] = {{0.666667, 2.33333},},
    ["AE_Transform_217-effect0"] = {{0.333333, 2.33333},},
    ["LumiLayerBlend_217-blend"] = {{0.333333, 2.33333},},
}
data.ae_durations = ae_durations

local ae_compDurations = {0.333333, 1.800000}
data.ae_compDurations = ae_compDurations

local ae_durationMode = 0 
data.ae_durationMode = ae_durationMode

local ae_disappearTime = 0.000000 
data.ae_disappearTime = ae_disappearTime

local ae_effectType = "transition" 
data.ae_effectType = ae_effectType

local ae_attribute = {
    ["AE_Transform_21-trs"] = {
        ["anchorPoint"] = Amaz.Vector3f(540, 960, 0),
        ["position"] = Amaz.Vector3f(540, 960, 0),
        ["scale"] = Amaz.Vector3f(100, 100, 100),
        ["orientation"] = Amaz.Vector3f(0, 0, 0),
        ["xRotation"] = 0,
        ["yRotation"] = 0,
        ["rotation"] = 0,
        ["opacity"] = 100,
        ["compositeSize"] = Amaz.Vector2f(1080, 1920),
        ["layerSize"] = Amaz.Vector2f(1080, 1920),
        ["mirrorEdge"] = false,
    },
    ["LumiLayerBlend_21-blend"] = {
        ["blendMode"] = "Normal",
        ["layerType"] = "Precomp",
    },
    ["LumiDirectionBlur_208-effect0"] = {
        ["angle"] = 90,
        ["intensity"] = 0,
        ["steps"] = 0,
        ["mirrorEdge"] = false,
        ["expandFlag"] = false,
    },
    ["lumi_motion_blur_2d_208-effect1"] = {
        ["rotate"] = 0,
        ["ae_pre_rotate"] = 0,
        ["anchor"] = Amaz.Vector2f(0.5, 0.5),
        ["ae_pre_anchor"] = Amaz.Vector2f(0.5, 0.5),
        ["position"] = Amaz.Vector2f(0.5, 0.5),
        ["ae_pre_position"] = Amaz.Vector2f(0.5, 0.5),
        ["scale_x"] = 1,
        ["ae_pre_scale_x"] = 1,
        ["scale_y"] = 1,
        ["ae_pre_scale_y"] = 1,
        ["vIntensity"] = 0,
        ["ae_pre_vIntensity"] = 0,
        ["vCenter"] = 0,
        ["ae_pre_vCenter"] = 0,
        ["minSamples"] = 0.1,
        ["ae_pre_minSamples"] = 0.1,
        ["maxSamples"] = 0.3,
        ["ae_pre_maxSamples"] = 0.3,
        ["mirrorEdge"] = true,
        ["ae_pre_mirrorEdge"] = true,
        ["dither"] = 1,
        ["ae_pre_dither"] = 1,
    },
    ["LumiLayerBlend_208-blend"] = {
        ["blendMode"] = "Normal",
        ["layerType"] = "Adjustment",
    },
    ["AE_Transform_210-effect0"] = {
        ["active_cam_fovx"] = 39.6,
        ["composite_size_x"] = 1080,
        ["composite_size_y"] = 1920,
        ["layer_size_x"] = 1080,
        ["layer_size_y"] = 1920,
        ["pivot_x"] = 540,
        ["pivot_y"] = 960,
        ["pivot_z"] = 0,
        ["position_x"] = 540,
        ["position_y"] = 960,
        ["position_z"] = 0,
        ["scale_x"] = 100,
        ["scale_y"] = 100,
        ["scale_z"] = 100,
        ["direction_x"] = 0,
        ["direction_y"] = 0,
        ["direction_z"] = 0,
        ["xRotation"] = 0,
        ["yRotation"] = 0,
        ["rotation"] = 0,
        ["opacity"] = 100,
        ["mirrorEdge"] = false,
    },
    ["LumiLayerBlend_210-blend"] = {
        ["blendMode"] = "Normal",
        ["layerType"] = "Adjustment",
    },
    ["AE_Transform_217-effect0"] = {
        ["active_cam_fovx"] = 39.6,
        ["composite_size_x"] = 1080,
        ["composite_size_y"] = 1920,
        ["layer_size_x"] = 1080,
        ["layer_size_y"] = 1920,
        ["pivot_x"] = 540,
        ["pivot_y"] = 960,
        ["pivot_z"] = 0,
        ["position_x"] = 540,
        ["position_y"] = 960,
        ["position_z"] = 0,
        ["scale_x"] = 100,
        ["scale_y"] = 100,
        ["scale_z"] = 100,
        ["direction_x"] = 0,
        ["direction_y"] = 0,
        ["direction_z"] = 0,
        ["xRotation"] = 0,
        ["yRotation"] = 0,
        ["rotation"] = 0,
        ["opacity"] = 100,
        ["mirrorEdge"] = false,
    },
    ["LumiLayerBlend_217-blend"] = {
        ["blendMode"] = "Normal",
        ["layerType"] = "Adjustment",
    },
}
data.ae_attribute = ae_attribute

local ae_keyframes = {
    ["AE_Transform_21-trs#opacity#number"] =
{
	{
		{0.166666667, 0.166666667, 0.833333333, 0.833333333, }, 
		{0.866667, 1, }, 
		{{100, }, {0, }, }, 
		{6417, }, 
		{1, }, 
	}, 
},
    ["LumiDirectionBlur_208-effect0#intensity#number"] =
{
	{
		{0.166666667, 0, 0.9, 1, }, 
		{0.666667, 0.766667, }, 
		{{0, }, {80, }, }, 
		{6417, }, 
		{0, }, 
	}, 
	{
		{0.1, 0, 0.915491936, 0.999999978, }, 
		{0.766667, 1, }, 
		{{80, }, {0, }, }, 
		{6417, }, 
		{0, }, 
	}, 
},
    ["LumiDirectionBlur_208-effect0#steps#number"] =
{
	{
		{0.166666667, 0, 0.9, 1, }, 
		{0.666667, 0.766667, }, 
		{{0, }, {3, }, }, 
		{6417, }, 
		{0, }, 
	}, 
	{
		{0.1, 0, 0.9999, 0.999999999, }, 
		{0.766667, 1, }, 
		{{3, }, {0, }, }, 
		{6417, }, 
		{0, }, 
	}, 
},
    ["lumi_motion_blur_2d_208-effect1#ae_pre_position#vector"] =
{
	{
		{0.708842, 0, 0.799848, 0.701855, }, 
		{0.70000033333333, 1.03333333333333, }, 
		{{0.5, 0.5, }, {-1.32493475998796, 0.5, }, {0.5, 0.5, }, {-1.32493475998796, 0.5, }, }, 
		{6415, }, 
		{0, }, 
	}, 
	{
		{0.176485, 1, 0.579452, 1, }, 
		{1.03333333333333, 1.20000033333333, }, 
		{{-1.32493475998796, 0.5, }, {-1.56481481481481, 0.5, }, {-1.32493475998796, 0.5, }, {-1.56481481481481, 0.5, }, }, 
		{6415, }, 
		{0, }, 
	}, 
	{
		{0.315093, 0, 0.43507, 1, }, 
		{1.20000033333333, 1.80000033333333, }, 
		{{-1.56481481481481, 0.5, }, {-1.5, 0.5, }, {-1.56481481481481, 0.5, }, {-1.5, 0.5, }, }, 
		{6415, }, 
		{0, }, 
	}, 
},
    ["lumi_motion_blur_2d_208-effect1#position#vector"] =
{
	{
		{0.708842, 0, 0.799848, 0.701855, }, 
		{0.666667, 1, }, 
		{{0.5, 0.5, }, {-1.32493475998796, 0.5, }, {0.5, 0.5, }, {-1.32493475998796, 0.5, }, }, 
		{6415, }, 
		{0, }, 
	}, 
	{
		{0.176485, 1, 0.579452, 1, }, 
		{1, 1.166667, }, 
		{{-1.32493475998796, 0.5, }, {-1.56481481481481, 0.5, }, {-1.32493475998796, 0.5, }, {-1.56481481481481, 0.5, }, }, 
		{6415, }, 
		{0, }, 
	}, 
	{
		{0.315093, 0, 0.43507, 1, }, 
		{1.166667, 1.766667, }, 
		{{-1.56481481481481, 0.5, }, {-1.5, 0.5, }, {-1.56481481481481, 0.5, }, {-1.5, 0.5, }, }, 
		{6415, }, 
		{0, }, 
	}, 
},
    ["lumi_motion_blur_2d_208-effect1#ae_pre_vIntensity#number"] =
{
	{
		{0.166666667, 0, 0.9, 1, }, 
		{0.70000033333333, 0.80000033333333, }, 
		{{0, }, {2, }, }, 
		{6417, }, 
		{0, }, 
	}, 
	{
		{0.1, 0, 0.915491936, 0.999999985, }, 
		{0.80000033333333, 1.20000033333333, }, 
		{{2, }, {0, }, }, 
		{6417, }, 
		{0, }, 
	}, 
},
    ["lumi_motion_blur_2d_208-effect1#vIntensity#number"] =
{
	{
		{0.166666667, 0, 0.9, 1, }, 
		{0.666667, 0.766667, }, 
		{{0, }, {2, }, }, 
		{6417, }, 
		{0, }, 
	}, 
	{
		{0.1, 0, 0.915491936, 0.999999985, }, 
		{0.766667, 1.166667, }, 
		{{2, }, {0, }, }, 
		{6417, }, 
		{0, }, 
	}, 
},
    ["AE_Transform_210-effect0#scale_x#number"] =
{
	{
		{0.75, 0, 0.67, 1, }, 
		{0.666667, 1, }, 
		{{100, }, {150, }, }, 
		{6417, }, 
		{0, }, 
	}, 
	{
		{0.153497825, -4.9e-8, 0.263287057, 1.000000219, }, 
		{1, 1.766667, }, 
		{{150, }, {100, }, }, 
		{6417, }, 
		{0, }, 
	}, 
},
    ["AE_Transform_210-effect0#scale_y#number"] =
{
	{
		{0.75, 0, 0.67, 1, }, 
		{0.666667, 1, }, 
		{{100, }, {150, }, }, 
		{6417, }, 
		{0, }, 
	}, 
	{
		{0.153497825, -4.9e-8, 0.263287057, 1.000000219, }, 
		{1, 1.766667, }, 
		{{150, }, {100, }, }, 
		{6417, }, 
		{0, }, 
	}, 
},
    ["AE_Transform_217-effect0#scale_x#number"] =
{
	{
		{1, -1.77e-7, 0.830790557, 1.000000065, }, 
		{0.333333, 0.8, }, 
		{{100, }, {160, }, }, 
		{6417, }, 
		{0, }, 
	}, 
	{
		{0.75, 0, 0.833333333, 0.833333333, }, 
		{0.8, 1, }, 
		{{160, }, {100, }, }, 
		{6417, }, 
		{0, }, 
	}, 
},
    ["AE_Transform_217-effect0#scale_y#number"] =
{
	{
		{1, -1.77e-7, 0.830790557, 1.000000065, }, 
		{0.333333, 0.8, }, 
		{{100, }, {160, }, }, 
		{6417, }, 
		{0, }, 
	}, 
	{
		{0.75, 0, 0.833333333, 0.833333333, }, 
		{0.8, 1, }, 
		{{160, }, {100, }, }, 
		{6417, }, 
		{0, }, 
	}, 
},
}
data.ae_keyframes = ae_keyframes

local ae_transitionInputIndex = {
    {"AE_Transform_21-trs", "InputTex", 0},
    {"LumiLayerBlend_21-blend", "InputTex", 1},
}
data.ae_transitionInputIndex = ae_transitionInputIndex

local ae_sliderInfos = {
}
data.ae_sliderInfos = ae_sliderInfos


return data
