local exports = exports or {}
local MotionBlur2D = MotionBlur2D or {}
MotionBlur2D.__index = MotionBlur2D
---@class MotionBlur2D: ScriptComponent
---@field CurrRotate double [UI(Range={0, 360}, Slider)]
---@field CurrAnchor Vector2f [UI(Drag=0.01)]
---@field CurrPosition Vector2f [UI(Drag=0.01)]
---@field CurrScale Vector2f [UI(Drag=0.01)]
---@field vIntensity double [UI(Range={0, 2}, Slider)]
---@field vCenter double [UI(Range={-1, 1}, Slider)]
---@field minSamples double [UI(Range={0, 256}, Slider)]
---@field maxSamples double [UI(Range={0, 256}, Slider)]
---@field dither double [UI(Range={0, 1}, Slider)]
---@field mirrorEdge boolean
---@field InputTex Texture
---@field OutputTex Texture

function MotionBlur2D.new(construct, ...)
    local self = setmetatable({}, MotionBlur2D)
    if construct and MotionBlur2D.constructor then
        MotionBlur2D.constructor(self, ...)
    end
    self.startTime = 0.0
    self.endTime = 1.0
    self.curTime = 0.0
    self.firstSeek = true
    
    self.PrevRotate = 0
    self.PrevPosition = Amaz.Vector2f(0., 0.)
    self.PrevScale = Amaz.Vector2f(1, 1)
    self.PrevAnchor = Amaz.Vector2f(0., 0.)
    self.CurrRotate = 0
    self.CurrPosition = Amaz.Vector2f(0., 0.)
    self.CurrScale = Amaz.Vector2f(1, 1)
    self.CurrAnchor = Amaz.Vector2f(0., 0.)
    self.positionVec2Vector = Amaz.Vec2Vector()

    self.vIntensity = 1.0
    self.vCenter = 0.0
    self.minSamples = 2.0
    self.maxSamples = 24.0
    self.dither = 1.0
    self.mirrorEdge = false
    
    self.InputTex = nil
    self.OutputTex = nil
    return self
end

function MotionBlur2D:constructor()
end

function MotionBlur2D:onUpdate(comp, detalTime)
    self:seekToTime(comp, detalTime)

    self.material:setTex("u_inputImageTexture", self.InputTex)
    self.cam.renderTexture = self.OutputTex
end

function MotionBlur2D:start(comp)
    self.first = true
    self.material = comp.entity:searchEntity("motion_blur_2d"):getComponent("MeshRenderer").material
    self.cam = comp.entity:searchEntity("cam"):getComponent("Camera")
end

function MotionBlur2D:setEffectAttr(key, value, comp)
    local function _setEffectAttr(_key, _value)
        if self[_key] ~= nil then
            self[_key] = _value
            if comp and comp.properties ~= nil then
                comp.properties:set(_key, _value)
            end
        end
    end

    if key == "maxSamples" or key == "minSamples" then
        _setEffectAttr(key, math.floor(value * 100))
    elseif key == "rotate" then
        _setEffectAttr("CurrRotate", value)
    elseif key == "ae_pre_rotate" then
        _setEffectAttr("PrevRotate", value)
    elseif key == "scale_x" or key == "scale_y" then
        local CurrScale = self["CurrScale"]
        if CurrScale then
            if math.abs(value)<0.001 then value = 0.001 end
            if key == "scale_x" then
                CurrScale.x = value
            else
                CurrScale.y = value
            end
            _setEffectAttr("CurrScale", CurrScale)
        end
    elseif key == "position" then
        local CurrPosition = self["CurrPosition"]
        if CurrPosition then
            CurrPosition.x = value.x - 0.5
            CurrPosition.y = value.y - 0.5
            _setEffectAttr("CurrPosition", CurrPosition)
        end
    elseif key == "ae_pre_position" then
        local PrevPosition = self["PrevPosition"]
        if PrevPosition then
            PrevPosition.x = value.x - 0.5
            PrevPosition.y = value.y - 0.5
            _setEffectAttr("PrevPosition", PrevPosition)
        end
    elseif key == "anchor" then
        local CurrAnchor = self["CurrAnchor"]
        if CurrAnchor then
            CurrAnchor.x = value.x - 0.5
            CurrAnchor.y = value.y - 0.5
            _setEffectAttr("CurrAnchor", CurrAnchor)
        end
    elseif key == "ae_pre_anchor" then
        local PrevAnchor = self["PrevAnchor"]
        if PrevAnchor then
            PrevAnchor.x = value.x - 0.5
            PrevAnchor.y = value.y - 0.5
            _setEffectAttr("PrevAnchor", PrevAnchor)
        end
    elseif key == "ae_pre_scale_x" or key == "ae_pre_scale_y" then
        local PrevScale = self["PrevScale"]
        if PrevScale then
            if math.abs(value)<0.001 then value = 0.001 end
            if key == "ae_pre_scale_x" then
                PrevScale.x = value
            else
                PrevScale.y = value
            end
            _setEffectAttr("PrevScale", PrevScale)
        end
    else
        _setEffectAttr(key, value)
    end

end

function MotionBlur2D:seekToTime(comp, time)
    if self.first == nil then
        self:start(comp)
    end

    self.curTime = (self.curTime + time)%(self.endTime - self.startTime)

    local pointSize = 5;
    local pivotVec2Vector = Amaz.Vec2Vector()
    local positionVec2Vector = Amaz.Vec2Vector()
    local scaleVec2Vector = Amaz.Vec2Vector()
    local rotationFloatVector = Amaz.FloatVector()
    for i=0,pointSize,1 do
        local w = (self.vIntensity * (i/pointSize) + self.vCenter + 1.0);
        -- Offset keyframe with curve
        -- local frameTime = 1./ 90.0
        -- local AEprogress = progress + frameTime*(w-1.0)
        -- positionVec2Vector:pushBack(self:getOffset(AEprogress))
        local pivot = self.PrevAnchor * (1.0-w) + self.CurrAnchor * w;
        local position = self.PrevPosition * (1.0-w) + self.CurrPosition * w;
        local scale = self.PrevScale * (1.0-w) + self.CurrScale * w;
        local rotation = self.PrevRotate * (1.0-w) + self.CurrRotate * w;
        pivotVec2Vector:pushBack(pivot)
        positionVec2Vector:pushBack(position)
        scaleVec2Vector:pushBack(scale)
        rotationFloatVector:pushBack(rotation)
    end
    self.material:setVec2Vector("u_pivotVec2Vector", pivotVec2Vector)
    if self.positionVec2Vector:empty() then
        self.material:setVec2Vector("u_positionVec2Vector", positionVec2Vector)
    else
        self.material:setVec2Vector("u_positionVec2Vector", self.positionVec2Vector)
    end
    self.material:setVec2Vector("u_scaleVec2Vector", scaleVec2Vector)
    self.material:setFloatVector("u_rotationFloatVector", rotationFloatVector)

    self.material:setFloat("u_minSamples", self.minSamples);
    self.material:setFloat("u_maxSamples", self.maxSamples);
    self.material:setFloat("u_dither", self.dither);
    self.material:setFloat("u_mirrorEdge", self.mirrorEdge and 1 or 0)
end

function MotionBlur2D:onLateUpdate(comp, detalTime)

end

local function clamp(val, min, max)
    return math.max(math.min(val, max), min)
end

exports.MotionBlur2D = MotionBlur2D
return exports
