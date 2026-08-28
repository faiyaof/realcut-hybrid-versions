local LumiParamsSetter = {}
LumiParamsSetter.__index = LumiParamsSetter

function LumiParamsSetter.new(params, keyframes, sliderInfos, effectType)
    local self = setmetatable({}, LumiParamsSetter)
    self.params = params
    self.keyframes = keyframes
    self.sliderInfos = sliderInfos
    self.sliderParams = {}
    self.XTEvent = (effectType == 'xtFilter' or  effectType == 'xtEffect')
    return self
end

local function clamp(val, min, max)
    return math.max(math.min(val, max), min)
end

local function cvtTable2Amaz(attrType, v)
    local value = nil
    if attrType == "number" then
        if #v == 1 then
            value = v[1]
        else
            Amaz.LOGE("AE_LUA_TAG", "Invalid keyframe: " .. key .. " size: " .. #v)
        end
    elseif attrType == "vector" then
        if #v == 2 then
            value = Amaz.Vector2f(v[1], v[2])
        elseif #v == 3 then
            value = Amaz.Vector3f(v[1], v[2], v[3])
        elseif #v == 4 then
            value = Amaz.Vector4f(v[1], v[2], v[3], v[4])
        else
            Amaz.LOGE("AE_LUA_TAG", "Invalid keyframe: " .. key .. " size: " .. #v)
        end
    elseif attrType == "color" then
        if #v == 3 then
            value = Amaz.Color(v[1], v[2], v[3], 1.0)
        elseif #v == 4 then
            value = Amaz.Color(v[1], v[2], v[3], v[4])
        else
            Amaz.LOGE("AE_LUA_TAG", "Invalid keyframe: " .. key .. " size: " .. #v)
        end
    else
        Amaz.LOGE("AE_LUA_TAG", "Invalid keyframe: " .. key .. "unsupported type: " .. attrType)
    end
    return value
end

function LumiParamsSetter:getCurrentDefaultParam(entity, key, time)
    local keyframeName = entity..'#'..key.."#"..'number'
    local keyframeType = 'number'
    if self.keyframes.attrs[keyframeName] == nil then
        keyframeName = entity..'#'..key.."#"..'vector'
        keyframeType = 'vector'
        if self.keyframes.attrs[keyframeName] == nil then
            keyframeName = entity..'#'..key.."#"..'color'
            keyframeType = 'color'
            if self.keyframes.attrs[keyframeName] == nil then
                keyframeName = nil
            end
        end
    end
    local value = nil
    if keyframeName ~= nil  then
        value = cvtTable2Amaz(keyframeType, self.keyframes:GetVal(keyframeName, time))
    else
        local entity = self.params[entity]
        if entity ~= nil then
            value = entity[key]
        end
    end
    return value
end


function LumiParamsSetter:updateSlider(lumi_obj, startTime, endTime, curTime, aeTime)
    -- local sliderIntensity = self.sliderParams['effects_adjust_blur']
    -- local gaussianIntensity = self:getCurrentDefaultParam("Gaussian_Blur_Root_353-effect2", 'intensity', aeTime)
    -- if sliderIntensity and gaussianIntensity then
    --     lumi_obj:setSubEffectAttr("Gaussian_Blur_Root_353-effect2", 'intensity', gaussianIntensity*sliderIntensity)
    -- end

    for sliderKey, paramsInfos in pairs(self.sliderInfos) do
        if self.sliderParams[sliderKey] ~= nil then
            for index, value in ipairs(paramsInfos) do
                local sliderIntensity = self.sliderParams[sliderKey]
                local entityName = value[1]
                local paramKey = value[2]
                local caluType = value[3]
                local maxValue = value[4]
                local minValue = value[5]
                local defaultValue = value[6]
                local valueA = value[7]
                local valueB = value[8]
                sliderIntensity = sliderIntensity * (maxValue - minValue) + minValue
                local oriValue = self:getCurrentDefaultParam(entityName, paramKey, aeTime)
                local newValue = oriValue
                if caluType == 0 then
                    newValue = (oriValue - sliderIntensity) * valueA + valueB
                elseif caluType == 1 then
                    newValue = (oriValue - valueA) * sliderIntensity + valueB
                elseif caluType == 2 then
                    newValue = (oriValue - valueA) * valueB + sliderIntensity
                end
                lumi_obj:setSubEffectAttr(entityName, paramKey, newValue)
            end
        end
    end

end


function LumiParamsSetter:onEvent(lumi_obj, event)
    if lumi_obj == nil or event == nil then return end
        local key = event.args:get(0)
        if self.sliderInfos[key] ~= nil then
            if self.XTEvent then
                self.sliderParams[key] = event.args:get(2);
            else
                self.sliderParams[key] = event.args:get(1);
            end
        end
    -- end
end

function LumiParamsSetter:initParams(lumi_obj)
    if lumi_obj == nil then return end
    if self.params == nil then return end
    if self.init then return end

    for entityName, params in pairs(self.params) do
        for key, value in pairs(params) do
            lumi_obj:setSubEffectAttr(entityName, key, value)
        end
    end

    self.init = true
end

function LumiParamsSetter:updateKeyFrameData(lumi_obj, startTime, endTime, curTime, aeTime)
    if lumi_obj == nil then return end
    if self.keyframes == nil then return end

    -- local p = (curTime - startTime) / (endTime - startTime)
    local p = aeTime
    for key, _ in pairs(self.keyframes.attrs) do
        local keys = {}
        for substr in string.gmatch(key, "[^#]+") do
            table.insert(keys, substr)
        end
        if #keys == 3 then
            local entityName = keys[1]
            local attrName = keys[2]
            local attrType = keys[3]
            local v = self.keyframes:GetVal(key, p)
            local value = cvtTable2Amaz(attrType, v)
            if value then
                lumi_obj:setSubEffectAttr(entityName, attrName, value)
            end
        else
            Amaz.LOGE("AE_LUA_TAG", "Invalid keyframe: " .. key)
        end
    end
end

return LumiParamsSetter
