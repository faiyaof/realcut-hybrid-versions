local exports = exports or {}
local LumiLayerBlend = LumiLayerBlend or {}
LumiLayerBlend.__index = LumiLayerBlend
---@class LumiLayerBlend: ScriptComponent
---@field blendMode string [UI(Option={"Normal", "Add", "Multiply", "Difference", "Overlay", "Darken", "Lighten", "SoftLight", "HardLight", "Hue", "Saturation", "Color", "Screen", "ColorBurn", "LinearBurn", "ColorDodge", "LinearDodge", "VividLight", "LinearLight", "PinLight", "HardMix", "Exclusion", "Subtract", "Divide", "Luminosity", "LighterColor", "DarkerColor", "Dissolve"})]
---@field needBlend boolean
---@field layerType string [UI(Option={"Adjustment", "Precomp", "Solid", "Image", "Video", "Sequence"})]
---@field SourceTex Texture
---@field InputTex Texture
---@field OutputTex Texture

local BlendModeName = {
    "Normal", "Add", "Multiply", "Difference", "Overlay", "Darken", "Lighten", "SoftLight", "HardLight", "Hue", "Saturation", "Color", "Screen", "ColorBurn", "LinearBurn", "ColorDodge", "LinearDodge", "VividLight", "LinearLight", "PinLight", "HardMix", "Exclusion", "Subtract", "Divide", "Luminosity", "LighterColor", "DarkerColor", "Dissolve"
}
setmetatable(BlendModeName, {__index = function(_, _) return BlendModeName[1] end})

local BlendModeIndex = {}
for index, value in ipairs(BlendModeName) do BlendModeIndex[value] = index - 1 end
setmetatable(BlendModeIndex, {
    __index = function(_, key)
        Amaz.LOGE("AE_LUA_TAG", "Unsupported blend mode: " .. key)
        return 0
    end
})

function LumiLayerBlend.new(construct, ...)
    local self = setmetatable({}, LumiLayerBlend)

    if construct and LumiLayerBlend.constructor then LumiLayerBlend.constructor(self, ...) end

    self.SourceTex = nil
    self.InputTex = nil
    self.OutputTex = nil
    self.blendMode = "Normal"
    self.needBlend = true
    self.layerType = 'Adjustment'

    return self
end

function LumiLayerBlend:constructor()
end

function LumiLayerBlend:onStart(comp)
    self.name = comp.entity.name
    self.camera = comp.entity:searchEntity("BlendCamera"):getComponent("Camera")
    self.material = comp.entity:searchEntity("BlendPass"):getComponent("MeshRenderer").material
end

function LumiLayerBlend:setVisible(visible)
    self.needBlend = visible
end

function LumiLayerBlend:onUpdate(comp, deltaTime)
    self.camera.renderTexture = self.OutputTex
    self.material:setTex("u_BaseTexure", self.InputTex)
    self.material:setTex("u_SourceTexture", self.SourceTex)
    self.material:setInt("u_BlendMode", BlendModeIndex[self.blendMode])
    self.material:setInt("u_NeedBlend", self.needBlend and 1 or 0)
    self.material:setInt("u_layerType", self.layerType == 'Adjustment' and 1 or 0)
end

exports.LumiLayerBlend = LumiLayerBlend
return exports
