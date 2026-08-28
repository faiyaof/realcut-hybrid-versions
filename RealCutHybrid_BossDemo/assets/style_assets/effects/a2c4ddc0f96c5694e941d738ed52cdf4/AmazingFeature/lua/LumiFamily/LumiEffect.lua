      
local isEditor = (Amaz.Macros and Amaz.Macros.EditorSDK) and true or false
local exports = exports or {}
local LumiEffect = LumiEffect or {}
LumiEffect.__index = LumiEffect
---@class LumiEffect : ScriptComponent
---@field InputTex Texture
---@field OutputTex Texture

function LumiEffect.new(construct, ...)
    local self = setmetatable({}, LumiEffect)

    self.__lumi_type = "lumi_effect"
    self.__lumi_rt_pingpong_type = "custom"

    if construct and LumiEffect.constructor then LumiEffect.constructor(self, ...) end
    return self
end


function LumiEffect:constructor()

end

function LumiEffect:onStart(comp)
    self.entity = comp.entity
    self.trans = self.entity:getComponent("Transform")
end

function LumiEffect:onDestroy(comp)
    
end


function LumiEffect:updateMaterials(comp, deltaTime)
    
end

function LumiEffect:onUpdate(comp, deltaTime)

    -- self:updateMaterials(comp, deltaTime)
end

exports.LumiEffect = LumiEffect
return exports
