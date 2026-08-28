      
local isEditor = (Amaz.Macros and Amaz.Macros.EditorSDK) and true or false
local exports = exports or {}
local LumiDirectionBlur = LumiDirectionBlur or {}
LumiDirectionBlur.__index = LumiDirectionBlur
---@class LumiDirectionBlur : ScriptComponent
---@field InputTex Texture
---@field OutputTex Texture
---@field angle double
---@field intensity number
---@field mirrorEdge boolean
---@field steps number

function LumiDirectionBlur.new(construct, ...)
    local self = setmetatable({}, LumiDirectionBlur)

    if construct and LumiDirectionBlur.constructor then LumiDirectionBlur.constructor(self, ...) end

    self.InputTex = nil
    self.OutputTex = nil

    self.angle = 0.0
    self.intensity = 0.0
    self.steps = 1.0
    self.expandFlag = false
    self.mirrorEdge = false

    return self
end

function LumiDirectionBlur:constructor()
end

function LumiDirectionBlur:onStart(comp)
    self.camera = comp.entity:searchEntity("BlitCamera"):getComponent("Camera")
    self.material = comp.entity:searchEntity("BlitPass"):getComponent("MeshRenderer").material
end

function LumiDirectionBlur:onUpdate(comp, deltaTime)
    if self.OutputTex then
        self.camera.renderTexture = self.OutputTex
    end
    self.material:setTex("u_InputTexture", self.InputTex)

    self.material:setFloat('u_Angle', 90-self.angle)
    self.material:setFloat('u_Steps', self.steps)
    self.material:setFloat('u_Sample',  math.floor(self.intensity))
    self.material:setFloat('u_ExpandFlag', self.expandFlag and 1 or 0)
    self.material:setFloat('u_mirrorEdge', self.mirrorEdge and 1 or 0)
end

exports.LumiDirectionBlur = LumiDirectionBlur
return exports
